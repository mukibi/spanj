#!/usr/bin/perl

use strict;
use warnings;
use feature "switch";

use DBI;
use Fcntl qw/:flock SEEK_END/;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d);

my %session;
my %auth_params;

my $logd_in = 0;
my $authd = 0;

my $page = 1;
my $per_page = 10;
my $mode_str = "";
my $search_mode = 0;

my $con;

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		my $id = $session{"id"};
		if ($id eq "1") {
			$authd++;
		}
	}

	if (exists $session{"view_per_page"} and $session{"view_per_page"} =~ /^(\d+)$/) {
		$per_page = $1;
	}
}

my $content = "";
my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/yans/">Yans Timetable Builder</a> --&gt; <a href="/cgi-bin/editteacherlist.cgi">Edit Teacher List</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Edit Teacher List</title>
</head>
<body>
$header
<p><span style="color: red">Sorry, you do not have the appropriate privileges to edit the list of teachers.</span> Only the administrator is authorized to take this action.
</body>
</html> 
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/editteacherlist.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Yans: Timetable Builder - Edit Teacher List</title>
</head>
<body>
You should have been redirected to <a href="/login.html?cont=/cgi-bin/editteacherlist.cgi">/login.html?cont=/cgi-bin/editteacherlist.cgi</a>. If you were not, <a href="/cgi-bin/editteacherlist.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

if ( exists $ENV{"QUERY_STRING"} ) {
	if ( $ENV{"QUERY_STRING"} =~ /\&?pg=(\d+)\&?/ ) {	
		$page = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?per_page=(\d+)\&?/ ) {
			
		my $possib_per_page = $1;
		
		if (($possib_per_page % 10) == 0) { 	
			$per_page = $possib_per_page;
		}
		else {
			if ($possib_per_page < 10) {	
				$per_page = 10;
			}
			else {
				$per_page = substr("".$possib_per_page, 0, -1) . "0";
			}	
		}
		#when the user changes the results per
		#page to more results per page, they should
		#be sent a page down.
		#if they select fewer results per page, they should
		#be sent a page up.
		$session{"view_per_page"} = $per_page;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?mode=search\&?/i ) {
		$search_mode++;
		$mode_str = "&mode=search";	
	}
}

my $post_mode = 0;
if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	
	my $str = "";

	while (<STDIN>) {
               	$str .= $_;
       	}

	my $space = " ";
	$str =~ s/\x2B/$space/ge;
	my @auth_req = split/&/,$str;

	for my $auth_req_line (@auth_req) {
		my $eqs = index($auth_req_line, "=");	
		if ($eqs > 0) {
			my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1)); 
			$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$auth_params{$k} = $v;
		}
	}
	$post_mode++;
}

if ($post_mode) {
	
	my $error_msg = undef;
	if (exists $session{"confirm_code"} and exists $auth_params{"confirm_code"}) {
		unless ( $session{"confirm_code"} eq $auth_params{"confirm_code"}) {
			$error_msg = "The validation token sent with this request does not correspond to the one saved on the server. Refresh this page to get fresh tokens.";
		}
	}
	else {
		$error_msg = "No validation token was received with this request. Refresh this page to receive fresh tokens.";
	}
	if (defined $error_msg) {
		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Edit Teacher List</title>
</head>
<body>
$header
<p><span style="color: red">$error_msg</span>
</body>
</html>
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;	
	}
}

my $order_by_clause = "ORDER BY id DESC";
#most recent ORDER BY statement should take precedence over
#previous ORDER BYs
my ($order_by, $sort_order);

if (exists $auth_params{"sort_by"} ) {	
	#Request will result in re-ordering of results
	#Therefore, jumps to page 1
	if (exists $session{"ta_sort_by"} and ($session{"ta_sort_by"} ne $auth_params{"sort_by"})) {
		$page = 1;
	}

	if (exists $session{"ta_sort_order"} and exists $auth_params{"sort_order"} and ($session{"ta_sort_order"} ne $auth_params{"sort_order"})) {
		$page = 1;
	}
	
	$order_by = lc($auth_params{"sort_by"});	
	my $user_ordered = 0;

	given ($order_by) {
		when ("id") {$user_ordered++;$order_by_clause = "ORDER BY id"}
		when ("name") {$user_ordered++;$order_by_clause = "ORDER BY name"}
		when ("subjects_classes") {$user_ordered++;$order_by_clause = "ORDER BY count_str(subjects, ',') + count_str(subjects, ';')"}
	}

	if ($user_ordered) {
		$session{"ta_sort_by"} = $order_by;
		my $valid_sort_order = 0;
		if (exists $auth_params{"sort_order"}) {
			$sort_order = $auth_params{"sort_order"};	
			given ($sort_order) {
				when ("0") {$valid_sort_order++; $order_by_clause .= " DESC"}
				when ("1") { $valid_sort_order++; $order_by_clause .= " ASC"}
			}
		}
		unless ($valid_sort_order) {
			$order_by_clause .= " DESC"; 	
		}
		else {	
			$session{"ta_sort_order"} = $sort_order;	
		}
	}
}

elsif (exists $session{"ta_sort_by"} ) {
	$order_by = lc($session{"ta_sort_by"});		
	my $user_ordered = 0;

	given ($order_by) {
		when ("id") {$user_ordered++;$order_by_clause = "ORDER BY id"}
		when ("name") {$user_ordered++;$order_by_clause = "ORDER BY name"}
		when ("subjects") {$user_ordered++;$order_by_clause = "ORDER BY count_str(subjects, ',') + count_str(subjects, ';')"}
	}

	if ($user_ordered) {
		my $sort_order;
		my $valid_sort_order = 0;
		if (exists $session{"ta_sort_order"}) {
			$sort_order = $session{"ta_sort_order"};	
			given ($sort_order) {
				when ("0") {$valid_sort_order++; $order_by_clause .= " DESC"}
				when ("1") { $valid_sort_order++; $order_by_clause .= " ASC"}
			}
		}
		unless ($valid_sort_order) {
			$order_by_clause .= " DESC"; 
		}
	}
}

my $search_str = "";
my $name_match_clause = "";

if ($search_mode) {
	#search term in POSTd data
	if ( exists $auth_params{"search"} ) {
		if (exists $auth_params{"confirm_code"} and exists $session{"confirm_code"}) {
			if ($auth_params{"confirm_code"} eq $session{"confirm_code"}) {	
				$name_match_clause = "WHERE name LIKE ? OR subjects LIKE ? ";	
				$session{"search"} = $auth_params{"search"};
				$search_str = $auth_params{"search"};
			}
			else {
				$search_mode = 0;
			}
		}
		else {
			$search_mode = 0;
		}
	}
	#search term in session data
	elsif (exists $session{"search"}) {	
		$name_match_clause = "WHERE name LIKE ? OR subjects LIKE ? ";
		$search_str = $session{"search"};
	}
	#No search term in POSTed data or session
	#Just clear the search mode flag
	else {
		$search_mode = 0;
		$mode_str = "";
	}
}

my $add_teacher_feedback = "";

my $yrs_study = 4;
my ($min_class, $max_class) = (1,4);

my @classes = ("1", "2", "3", "4");
my @subjects = ("Mathematics", "English", "Kiswahili", "History", "CRE", "Geography", "Physics", "Chemistry", "Biology", "Computers", "Business Studies", "Home Science");


$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});		

if ($con) {
	my $prep_stmt0 = $con->prepare("SELECT id,value FROM vars WHERE id='1-classes' OR id='1-subjects' LIMIT 2");
	if ($prep_stmt0) {
		my $rc = $prep_stmt0->execute();	
		if ($rc) {	
			while (my @valid = $prep_stmt0->fetchrow_array()) {
				#did away with the set default classes/subjects business
				#reason: the defalt values have already been nicely set in a convenient format:
				#perl code.
				#
				#classes 
				if ($valid[0] eq "1-classes") {
					my ($min_class, $max_class) = (undef,undef);
					@classes  =  split/,\s*/, $valid[1];
					foreach (@classes) {
						if ($_ =~ /(\d+)/) {
							my $tst_yr = $1;
							if (not defined $min_class) {
								$min_class = $tst_yr;
								$max_class = $tst_yr;
							}
							else {
								$min_class = $tst_yr if ($tst_yr < $min_class);
								$max_class = $tst_yr if ($tst_yr > $max_class);
							}
						}
						$yrs_study = ($max_class - $min_class) + 1;
					}
				}
				#subjects
				else {
					@subjects = split/,\s*/, $valid[1];
				}
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM vars: ", $prep_stmt0->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT FROM vars statement: ", $prep_stmt0->errstr, $/;  
	}
}


#what is th time
my @today = localtime;
my $current_yr = $today[5] + 1900;

#user wants to add a teacher
#do it.

if (exists $auth_params{"save"}) {
	
	#replicated code
	#already handled by $post_mode
	if (exists $auth_params{"confirm_code"} and exists $session{"confirm_code"} and $auth_params{"confirm_code"} eq $session{"confirm_code"}) {
	my $valid_ta_name = 1;
	my $ta = undef;

	#is there a teacher name; any name
	if ( exists $auth_params{"teacher_name"} ) {
		$ta = $auth_params{"teacher_name"};
		my $ta_len = length($ta);
		#is it the right length
		if ( $ta_len > 0 and $ta_len <= 80 ) {
			#is it the right chars
			unless ($ta =~ /^[a-zA-Z\-\'\s\.]{1,80}$/) {
				$valid_ta_name = 0;
				$add_teacher_feedback = "Invalid characters in the teacher name. Valid characters are: A-Z (upper and lower case), -, ' and spaces. The teacher was not added.";
			}
		}
		else {
			$valid_ta_name = 0;
			$add_teacher_feedback = "Invalid teacher name. A valid teacher name must be 1-80 characters long. The teacher was not added";
		}
	}
	else {
		$add_teacher_feedback = "Invalid teacher name. No name provided for the teacher. The teacher was not added.";
		$valid_ta_name = 0;
	}

	my $ta_id = "0";
	if (exists $auth_params{"teacher_id"}) {
		if ($auth_params{"teacher_id"} =~ /^[0-9]+$/) {
			$ta_id = $auth_params{"teacher_id"};
		}
	}

	my (%subjs_hash, %classes_hash);

	@subjs_hash{@subjects} = @subjects;
	@classes_hash{@classes} = @classes;
	
	my @reformed_subj_classes = ();

	for my $param (keys %auth_params) {

		if ($param =~ /^subject_(.+)$/) {
			my $subj = $1;
			
			if (exists $subjs_hash{$subj}) {	

				my $classes = $auth_params{$param};
				
				my @classes_lst = split/,/,$classes;
				my @reformed_classes = ();

				for my $class ( @classes_lst ) {	
					if ( exists $classes_hash{$class} ) {
						if ( $class =~ /(\d+)/ ) {
							my $class_yr = $1;
							my $grad_yr = $current_yr + ($yrs_study - $class_yr);
							push @reformed_classes, qq!$class($grad_yr)!;						
						}
					}
				}

				if (@reformed_classes) {	
					my $reformed_subj_class = $subj . "[" . join(",", @reformed_classes) . "]";
					push @reformed_subj_classes, $reformed_subj_class;	
				}
			}
		}
	}

	my $subj_classes_str = join(";", @reformed_subj_classes);
	
	if ($valid_ta_name) {
		unless ($con) {
			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});		
		}
		if ($con) {

			my $prep_stmt3 = $con->prepare("REPLACE INTO teachers values(?,?,?)");
			if ($prep_stmt3) {
				my $rc = $prep_stmt3->execute($ta_id, $ta, $subj_classes_str);
				if ($rc) {
					$con->commit();
					#log this addition
					my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
					open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

        				if ($log_f) {
                				@today = localtime;
						my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
						flock($log_f, LOCK_EX) or print STDERR "Could not log add teacher due to flock issue: $!$/";

						seek($log_f, 0, SEEK_END);

                				print $log_f $session{"id"}, " ADD TEACHER $ta $subj_classes_str $time\n";	

						flock ($log_f, LOCK_UN);
                				close $log_f;
        				}

					else {
						print STDERR "Could not log ADD TEACHER $session{'id'}: $!\n";
					}

				}
				else {
					print STDERR "Could not execute INSERT INTO teachers statement: ", $prep_stmt3->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare INSERT INTO teachers statement: ", $prep_stmt3->errstr, $/;
			}
		}
	}
	}
	else {
		$add_teacher_feedback .= "Invalid confirmation token received. Do not alter any of the values in the HTTP form.";
	}
}
if (exists $auth_params{"delete"}) {

	if (exists $auth_params{"confirm_code"} and exists $session{"confirm_code"} and $auth_params{"confirm_code"} eq $session{"confirm_code"}) {
		if (exists $auth_params{"delete_list"}) {

			my @del_list = split/,/, $auth_params{"delete_list"};
			my @invalid_ids = ();
 
			my @valid_ids = ();

			foreach (sort {$a <=> $b} @del_list) {
				unless ($_ =~ /^\d+$/) {
					push @invalid_ids, htmlspecialchars($_);
				}
				else {
					push @valid_ids, $_;
				}
			}
	
			if (@valid_ids) {
				my @where_clause_bts = ();
				foreach (@valid_ids) {
					push @where_clause_bts, "id=?";
				}

				my $where_clause = join(" OR ", @where_clause_bts);

				unless ($con) {
					$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
				}

				if ($con) {
					my $prep_stmt4 = $con->prepare("DELETE FROM teachers WHERE $where_clause ORDER BY id ASC");
					if ($prep_stmt4) {
						my $rc = $prep_stmt4->execute(@valid_ids);
						if (not $rc == scalar(@valid_ids)) {
							#$rc contains the row_count of deleted rows
							#since delete was ORDERed BY id, the tail of the
							#sorted @valid_ids will contain the un-DELETEd ids
							#a splice of this sorted list leaves these surplus ids.
							my @undeleted = splice(@valid_ids, $rc);
							
								
							$add_teacher_feedback .= "Some of the teachers selected for deletion do not exist in the system: " . join(", ", @undeleted) . "<br>";
						}
					
						if ($rc) {
							$con->commit();
							#log this deletion
							my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
							open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

		 	       				if ($log_f) {
                						@today = localtime;
								my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
								flock($log_f, LOCK_EX) or print STDERR "Could not log add teacher due to flock issue: $!$/";

								seek($log_f, 0, SEEK_END);

								foreach (@valid_ids) {	
        		        					print $log_f $session{"id"}, " DELETE TEACHER $_ $time\n";
								}

								flock ($log_f, LOCK_UN);
                						close $log_f;
		        				}

							else {
								print STDERR "Could not log DELETE TEACHER $session{'id'}: $!\n";
							}
						}
						else {
							print STDERR "Could not execute DELETE FROM teachers statement: ", $prep_stmt4->errstr, $/;	
						}

					}
					else {
						print STDERR "Could not prepare DELETE FROM teachers statement: ", $prep_stmt4->errstr, $/;
					}
				}
			}

			if (@invalid_ids) {
				$add_teacher_feedback .= "An attempt was made to delete invalid Staff IDs: " . join(", ", @invalid_ids) . "<br>";
			}
			if (@valid_ids) {
				$add_teacher_feedback .= "The teachers with the following Staff IDs were deleted: " . join(", ", @valid_ids);
			}
		}
		else {
			$add_teacher_feedback .= "No teachers selected for deletion.";
		}
	}
	else {
		$add_teacher_feedback .= "Invalid confirmation token received. Do not alter any of the values in the HTTP form.";
	}
}
my $row_count =	0;

if ($search_mode) {
	unless($con) {
		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});		
	}

	if ($con) {
		my $prep_stmt2 = $con->prepare("SELECT count(id) FROM teachers WHERE name LIKE ? OR subjects LIKE ? LIMIT 1");
		if ($prep_stmt2) {
			my $rc2 = $prep_stmt2->execute("%".$search_str."%", "%".$search_str."%");
			if ($rc2) {
				my @rslts = $prep_stmt2->fetchrow_array();
				if (@rslts) {	
					$row_count = $rslts[0];
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM teachers statement: ", $prep_stmt2->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM teachers statement: ", $prep_stmt2->errstr, $/;
		}
	}
	else {
		print STDERR "Cannot connect: $con->strerr$/";
	}
}

else {
	unless ($con) {
  		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});		
	}

	if ($con) {
		my $prep_stmt2 = $con->prepare("SELECT count(id) FROM teachers LIMIT 1");
		if ($prep_stmt2) {
			my $rc2 = $prep_stmt2->execute();
			if ($rc2) {
				my @rslts = $prep_stmt2->fetchrow_array();
				if (@rslts) {	
					$row_count = $rslts[0];
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM teachers: ", $prep_stmt2->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM teachers: ", $prep_stmt2->errstr, $/;  
		}
	}
	else {
		print STDERR "Cannot connect: $con->strerr$/";
	}
}

my $res_pages = 1;
#simple logic
#if the remaining results ($row_count - x) overflow the current page (x = $page * $per_page)
#and you are on page 1 then this' a multi_page setup

$res_pages = $row_count / $per_page;
if ($res_pages > 1) {
	if (int($res_pages) < $res_pages) {
		$res_pages = int($res_pages) + 1;
	}
}
my $page_guide = '';

if ($res_pages > 1) {
	$page_guide .= '<table cellspacing="50%"><tr>';

	if ($page > 1) {
		$page_guide .= "<td><a href='/cgi-bin/editteacherlist.cgi?pg=".($page - 1) . $mode_str ."'>Prev</a>";
	}

	if ($page < 10) {
		for (my $i = 1; $i <= $res_pages and $i < 11; $i++) {
			if ($i == $page) {
				$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
			}
			else {
				$page_guide .= "<td><a href='/cgi-bin/editteacherlist.cgi?pg=$i$mode_str'>$i</a>";
			}
		}
	}
	else {
		for (my $i = $page - 4; $i <= $res_pages and $i < ($page + 4); $i++) {
			if ($i == $page) {
				$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
			}
			else {
				$page_guide .= "<td><a href='/cgi-bin/editteacherlist.cgi?pg=$i$mode_str'>$i</a>";
			}
		}
	}
	if ($page < $res_pages) {
		$page_guide .= "<td><a href='/cgi-bin/editteacherlist.cgi?pg=".($page + 1).$mode_str."'>Next</a>";
	}
	$page_guide .= '</table>';
}

my $per_page_guide = '';

if ($row_count > 10) {
	$per_page_guide .= "<p><em>Results per page</em>: <span style='word-spacing: 1em'>";
	for my $row_cnt (10, 20, 50, 100) {
		if ($row_cnt == $per_page) {
			$per_page_guide .= " <span style='font-weight: bold'>$row_cnt</span>";
		}
		else {
			my $re_ordered_page = $page;	
			if ($page > 1) {
				my $preceding_results = $per_page * ($page - 1);
				$re_ordered_page = $preceding_results / $row_cnt;
				#if results will overflow into the next
				#page, bump up the page number
				#save that as an integer
				$re_ordered_page++ unless ($re_ordered_page < int($re_ordered_page));
				$re_ordered_page = int($re_ordered_page);	
			}	
			$per_page_guide .= " <a href='/cgi-bin/editteacherlist.cgi?pg=$re_ordered_page&per_page=$row_cnt$mode_str'>$row_cnt</a>";
		}
	}
	$per_page_guide .= "</span>";
}

my $limit_clause = ""; 	

if ($res_pages > 1) {
	my $offset = 0;
	if (exists $session{"view_per_page"}) {
		$offset = $session{"view_per_page"} * ($page - 1);	
		$limit_clause = " LIMIT $offset,".$session{"view_per_page"};
	}
	else {
		$offset = $per_page * ($page - 1);  
		$limit_clause = " LIMIT $offset,$per_page";
	}
}

my @tas_vars = ();
my $current_tas = "";
my $cntr = 0;

if ($con) {
	
	my $prep_stmt = $con->prepare("SELECT id,name,subjects FROM teachers $name_match_clause$order_by_clause$limit_clause");
					
	if ($prep_stmt) {
		my $rc;
		if ($search_mode) {
			$rc = $prep_stmt->execute("%".$search_str. "%", "%".$search_str. "%");
		}
		else {
			$rc = $prep_stmt->execute();
		}

		if ($rc) {
			while (my @valid = $prep_stmt->fetchrow_array()) {
				
				#say English[1A(2016),2A(2015)];Kiswahili[3A(2014)]
				my $machine_class_subjs = $valid[2];
			
				#now i have 
				#[0]: English[1A(2016),2A(2015)]
				#[1]: Kiswahili[3A(2014)]
				my @subj_groups = split/;/, $machine_class_subjs;
				my @reformd_subj_group = ();

				#take English[1A(2016),2A(2015)]
				for my $subj_group (@subj_groups) {
					my ($subj,$classes_str);
					
					if ($subj_group =~ /^([^\[]+)\[([^\]]+)\]$/) {
						#English
						my $subj = $1;
						#1A(2016),2A(2015)
						my $classes_str = $2;	
						#[0]: 1A(2016)
						#[1]: 2A(2015)
						my @classes_list = split/,/, $classes_str;
						my @reformd_classes_list = ();

						#take 1A(2016) 	
						for my $class (@classes_list) {	
							if ($class =~ /\((\d+)\)$/) {	
								my $grad_yr = $1;	

								my $class_dup = $class;
								$class_dup =~ s/\($grad_yr\)//;

								if ($grad_yr >= $current_yr) {
									my $class_yr = $yrs_study - ($grad_yr - $current_yr);
									$class_dup =~ s/\d+/$class_yr/;
								}
								else {
									$class_dup =~ s/\d+/$yrs_study/;
									$class_dup .= "[Grad class of $grad_yr]";	
								}
								push @reformd_classes_list, $class_dup;
							}
						}
						my $reformd_classes_str = join(", ", @reformd_classes_list);
						push @reformd_subj_group, "$subj($reformd_classes_str)";
					}
				}
				my $subjs_classes_js = join(";", @reformd_subj_group);

				push @tas_vars, qq!{id:"$valid[0]", name:"$valid[1]", subjects:"$subjs_classes_js"}!;
				my $human_class_subjs = join("<br>", @reformd_subj_group);
	
				$cntr++;

				$current_tas .= qq{<tr><td><input type='checkbox' name='$valid[0]' id='$valid[0]' onclick="check_ta('$valid[0]','$valid[2]')"><td>$valid[0]<td>$valid[1]<td>$human_class_subjs};	
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM teachers statement: ", $prep_stmt->errstr, $/;
		}	
	}
	else {
		print STDERR "Could not prepare SELECT FROM teachers statement: ", $prep_stmt->errstr, $/;  
	}
}

my $tas_table = "";

if ($cntr == 0) {
	if ($search_mode) {
		$tas_table = '<span style="color: red">Your search \'' . htmlspecialchars($search_str) . '\' did not match any teachers, classes or subjects in the system.</span>'; 
	}
	else {
		$tas_table = '<em>No teachers to display.</em><br>';
	}
}

else {
	$tas_table = '<table border="1" cellpadding="5%"><thead><th><input type="checkbox" title="Select all on page" name="select_all" id="select_all" onclick="check_all()"><th>Staff ID<th>Name<th>Subjects/Classes Taught</thead>';
	$tas_table .= '<tbody>' . $current_tas. '</tbody></table>';
}
	
my $all_tas_var = '[]';

my $conf_code = gen_token();
$session{"confirm_code"} = $conf_code;
	
if ($cntr) {
	$all_tas_var = '[' . join(', ', @tas_vars) . ']';
}

my $sort_guide = '';	
if ($cntr > 0) { 
		$sort_guide = 
qq{
<P>
<form method="POST" action="/cgi-bin/editteacherlist.cgi?pg=$page$mode_str"> 
<input type="hidden" name="confirm_code" value="$conf_code">
<table cellpadding="5%">
<tr>
<td><label for="sort_by">Sort by</label>
<td><select name="sort_by" id="sort_by" onchange="customize_sort_description()">
};

	my $sort_by = "id";

	if (exists $session{"ta_sort_by"}) {
		$sort_by = $session{"ta_sort_by"};
	}

	#probably tired
	for (my $i = 0; $i < 3; $i++) {
		if ($i == 0) {
			if ($sort_by eq "id") {
				$sort_guide .= '<option selected value="id">Staff ID</option>'
			}
			else {
				$sort_guide .= '<option value="id">Staff ID</option>'
			}
		}
		elsif ($i == 1) {
			if ($sort_by eq "name") {
				$sort_guide .= '<option selected value="name">Name</option>'
			}
			else {
				$sort_guide .= '<option value="name">Name</option>'
			}
		}
		else {
			if ($sort_by eq "subjects_classes") {
				$sort_guide .= '<option selected value="subjects_classes">Number of Subjects/Classes taught</option>'
			}
			else {
				$sort_guide .= '<option value="subjects_classes">Number of Subjects/Classes taught</option>'
			}
		}
	}

	$sort_guide .=

	'</select>
	<td><label for="sort_order">Sort order</label>
	<td>
	<span id="sort_order_container">';

	my $sort_order = "0";

	if (exists $session{"ta_sort_order"}) {
		$sort_order = $session{"ta_sort_order"};
	}

	#outrageous code
	#certainly the reason I'll never work @ Google 

	#sort by id
	if ($sort_by eq "id") {
		#sort ascending 
		if ($sort_order eq "1") {
			$sort_guide .= 
			'<SELECT name="sort_order">
				<OPTION value="0">Highest Staff ID first</OPTION>
				<OPTION selected value="1">Lowest Staff ID first</OPTION>
			</SELECT>';
		}
		#sort descending
		else {
			$sort_guide .= 
			'<SELECT name="sort_order">
				<OPTION selected value="0">Highest Staff ID first</OPTION>
				<OPTION value="1">Lowest Staff ID first</OPTION>
			</SELECT>';
		}	
	}
	#sort by name
	elsif ($sort_by eq "name") {
		#sort ascending
		if ($sort_order eq "1") {
				$sort_guide .=
 				'<SELECT name="sort_order">"
					<OPTION value="0">Alphabetical order(Z-A)</OPTION>
					<OPTION selected value="1">Alphabetical order(A-Z)</OPTION>
				 </SELECT>';
		}
		#sort descending
		else {
			$sort_guide .=
  			'<SELECT name="sort_order">"
				<OPTION selected value="0">Alphabetical order(Z-A)</OPTION>
				<OPTION value="1">Alphabetical order(A-Z)</OPTION>
			 </SELECT>';
		}
	}
	#sort by subjects/classes taught
	else {
		#sort ascending
		if ($sort_order eq "1") {
			$sort_guide .=
 			'<SELECT name="sort_order">
				<OPTION value="0">Most - least subjects/classes taught</OPTION>
				<OPTION selected value="1">Least - most classes/subjects</OPTION>
			</SELECT>';
		}
		#sort descending
		else {
			$sort_guide .= 
 			'<SELECT name="sort_order">
				<OPTION selected value="0">Most - least subjects/classes taught</OPTION>
				<OPTION value="1">Least - most subjects/classes taught</OPTION>
			</SELECT>';
		}
	}
		
	$sort_guide .= 
qq{
</span>
<td><input type="submit" name="sort" value="Sort">	
</table>
</form>
};
}

my $search_bar = 
qq{
<form action="/cgi-bin/editteacherlist.cgi?pg=1&mode=search" method="POST">
<table cellpadding="10%">
<tr>
<td><input type="text" size="30" maxlength="50" name="search" value="$search_str">
<td><input type="submit" name="search_go" value="Search" title="Search">
<input type="hidden" name="confirm_code" value="$conf_code">
</table>
</form>
};


#prepare JS:- classes & subjects arrays

my @classes_js_array_bts  = ();
my @subjects_js_array_bts = ();	

foreach (sort { $a cmp $b } @classes) {	
	push @classes_js_array_bts, qq!"$_"!;
}

foreach (sort { $a cmp $b } @subjects) {
	push @subjects_js_array_bts, qq!"$_"!;
}

my $classes_var  = "[" . join(",", @classes_js_array_bts) . "]";
my $subjects_var = "[" . join(",", @subjects_js_array_bts) . "]";

$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Edit Teacher List</title>
<SCRIPT type="text/javascript">

	var selected_subjs = new Array();
	var all_tas = $all_tas_var;
	var selected_teachers = new Array();
	
	var classes  = $classes_var;
	var subjects = $subjects_var;	

	var old_content;

	var subj_collisions = new Array();

	var ta_edited = -1;

	function check_all() {
		var all_checked = document.getElementById("select_all").checked;
		if (all_checked) {
			selected_teachers = [];
			for (var ta in all_tas) {
				selected_teachers.push(ta.id);
			}
			document.getElementById("delete").disabled = false;
			document.getElementById("edit").disabled = true;
			document.getElementById("edit").title = "You can only edit 1 teacher at a time.";
		}
		else {
			selected_teachers = [];
			document.getElementById("delete").disabled = true;
			document.getElementById("edit").disabled = true;
		}

		for (var i = 0; i < all_tas.length; i++) {
			document.getElementById(all_tas[i].id).checked = all_checked;
		}
	}

	function check_ta(sup_id) {	
		if (document.getElementById(sup_id) != null) {
			if (document.getElementById(sup_id).checked) {
				selected_teachers.push(sup_id);	
				document.getElementById("delete").disabled = false;
				//you can only edit when just 1 teacher is selected
				if (selected_teachers.length == 1) {
					document.getElementById("edit").disabled = false;	
				}
				else {
					document.getElementById("edit").disabled = true;
					document.getElementById("edit").title = "You can only edit 1 teacher at a time.";
				}
			}
			else {
				for (var i = 0; i < selected_teachers.length; i++) {
					if (selected_teachers[i] === sup_id) {
						selected_teachers.splice(i, 1);
						break;
					}
				}
				if (selected_teachers.length == 0) {
					document.getElementById("delete").disabled = true;
					document.getElementById("edit").disabled = true;
				}
				else if (selected_teachers.length == 1) {
					document.getElementById("edit").disabled = false;
				}
				else {
					document.getElementById("edit").title = "You can only edit 1 teacher at a time.";
				}
			}
		}
	}

	function customize_sort_description() {
		var id_description =
					 '<SELECT name="sort_order">' +
						'<OPTION value="0">Highest Staff ID first</OPTION>' +
						'<OPTION value="1">Lowest Staff ID first</OPTION>' +
					 '</SELECT>';

		var name_description =
					 '<SELECT name="sort_order">' +
						'<OPTION value="0">Alphabetical order(Z-A)</OPTION>' +
						'<OPTION value="1">Alphabetical order(A-Z)</OPTION>' +
					'</SELECT>';

		var subjects_classes_description =
					'<SELECT name="sort_order">' +
						'<OPTION value="0">Most - least number of subjects/classes</OPTION>' +
						'<OPTION value="1">Least - most number of subjects/classes</OPTION>' +
					'</SELECT>';

		var new_description = id_description;
		var selected_sort_by = document.getElementById("sort_by").value.toLowerCase();
		
		switch (selected_sort_by) {
			case "name":
				new_description = name_description;
				break;

			case "subjects_classes":
				new_description = subjects_classes_description;
		}
		
		document.getElementById("sort_order_container").innerHTML = new_description;
	}

	function add_new_teacher() {
		document.getElementById("pre_conf").style.border = "2px solid black";
		document.getElementById("pre_conf").style.width = "600px";	
		document.getElementById("pre_conf").style.padding = "2%";	
		
		old_content = document.getElementById("pre_conf").innerHTML;

		document.getElementById("pre_conf").innerHTML = "";

			
		var new_content = '<div id="name_collision_msg"></div><div style="color: red" id="subject_collision_msg"></div><TABLE cellspacing="10%">';
		
		new_content += '<TR><TD><span id="name_collision_asterisk" style="color: red"></span><LABEL for="ta_name" style="font-weight: bold">Teacher\\'s&nbsp;Name: </LABEL><TD><INPUT type="text" name="ta_name" id="ta_name" size="40" maxlength="80" value="" onblur="check_name_collision()">';
		//new_content += "</TABLE><TABLE>";
		for (var j = 0; j < subjects.length; j++) {
			new_content += '<TR><TD><span style="color: red" id="' + subjects[j] + '_asterisk"></span><LABEL style="font-weight: bold">' + subjects[j] + '</LABEL><TD><DIV style="height: 50px; border: 1px solid black; overflow-y: scroll">';
			var any_year = "Any Year"
			for (var i = 0; i < classes.length; i++) {
				var elem_id = subjects[j] + "_" + classes[i];
				new_content += '<INPUT type="checkbox" onclick=\\'add_new_subj_class("' + subjects[j] + '", "' + classes[i]+ '")\\' id="' + elem_id + '"><label>' + classes[i] + '</label>&nbsp; ';
			}
			new_content += '</DIV>';
		}
		new_content += '<tr><td><INPUT type="button" name="save" value="Save" onclick="save()"><td><INPUT type="button" name="cancel" value="Cancel" onclick="cancel()">';

		document.getElementById("pre_conf").innerHTML = new_content;
	}

	function add_new_subj_class(subj, class_name) {
		if (document.getElementById(subj + "_" + class_name).checked) {
			//create this array element
			if ( !selected_subjs[subj] ) {
				selected_subjs[subj] = [];
			}
			selected_subjs[subj].push(class_name);
			var collision = check_subj_class_collision(subj, class_name);
			var collision_name = "";
			for (var tas_iter in all_tas) {
				if (all_tas[tas_iter].id == collision) {
					collision_name += collision + "(" + all_tas[tas_iter].name + ")"; 
				}
			}
			if (collision > -1) {
				document.getElementById(subj + "_asterisk").innerHTML = "\*";
				document.getElementById("subject_collision_msg").innerHTML = "";

				subj_collisions[subj + "(" + class_name + ")"] = collision_name;
				for (var subj_collision in subj_collisions) {	
					var collider = subj_collisions[subj_collision];
					if (collider) {	
						document.getElementById("subject_collision_msg").innerHTML += subj_collision + " has already been assigned to " + collider + "<br>";
					}
				}	
			}
		}
		else {
			for (var k = 0; k < selected_subjs[subj].length; k++) {
				if (selected_subjs[subj][k] === class_name) {
					selected_subjs[subj].splice(k, 1);
					//null 
					if (selected_subjs[subj].length == 0) {
						selected_subjs[subj] = null;
					}
					break;
				}
			}

			document.getElementById(subj + "_asterisk").innerHTML = "";
			document.getElementById("subject_collision_msg").innerHTML = "";

			subj_collisions[subj + "(" + class_name + ")"] = null;

			for (var subj_collision in subj_collisions) {		
				var collider = subj_collisions[subj_collision];
				if (collider != null) {	
					document.getElementById("subject_collision_msg").innerHTML += subj_collision + " has already been assigned to " + collider + "<br>";
				}
			}
		}
	}

	function check_name_collision() {
		var name = document.getElementById("ta_name").value;
		var collision = false;
		for (var ta in all_tas) {
			//seen_collision	
			if (all_tas[ta].id == ta_edited) {
				continue;
			}
			if (all_tas[ta].name === name) {
				document.getElementById("name_collision_asterisk").innerHTML = "\x2A";
				document.getElementById("name_collision_msg").innerHTML = '<span style="color: red">There is already a teacher with this name</span>. Although Yans can handle this name collision, users may have problems distinguishing these 2 users. Suggestion: add a title, an initial or extra name to distinguish this teacher';
				collision = true;
			}
		}
		if (!collision) {
			document.getElementById("name_collision_asterisk").innerHTML = "";
			document.getElementById("name_collision_msg").innerHTML = '';

		}
		return(collision);
	}

	function check_subj_class_collision(subj,class_name) {	
		var re = new RegExp(subj + "\\((.\*)\\)");
		for (var ta in all_tas) {
			if (all_tas[ta].id == ta_edited) {
				continue;
			}
			
			var classes = re.exec(all_tas[ta].subjects);
			if (classes) {	
				var cleaned_classes = classes[1].substr(1, classes[1].length - 2);
				var classes_list = cleaned_classes.split(", ");
				for (var l = 0; l < classes_list.length; l++) {	
					if (classes_list[l].toLowerCase() === class_name.toLowerCase()) {
						return all_tas[ta].id;
					}
				}
				break;
			}
		
		}
		return -1;
	}

	function save() {
		var name = document.getElementById("ta_name").value;		

		if (name.length == 0) {

			document.getElementById("name_collision_asterisk").innerHTML = "\x2A";
			document.getElementById("name_collision_msg").innerHTML = '<span style="color: red">No name given for this teacher</span>.';

			return(1);
		}	

		var clear = true;
		if (check_name_collision()) {
			clear = false;
			document.getElementById("pre_conf").innerHTML = "";
			document.getElementById("pre_conf").innerHTML += "<p><strong>NB: There's already a teacher with this name.</strong> This is not a problem for Yans but it can be a problem for human users.";
		}

		if (clear) {
			document.getElementById("pre_conf").innerHTML = "";
		}

		var selection_len = 0;
		for (var selected_subj in selected_subjs) {
			selection_len++;
		}

		if (selection_len == 0) {
			document.getElementById("pre_conf").innerHTML += "<p><strong>NB: No subjects/classes have been selected</strong>. You can still save this record as it is and edit it later.";
		}

		var collision_num = 0;
		var colliding_subjs = new Array();

		for (var colliding_subj in subj_collisions) {
			if (subj_collisions[colliding_subj] != null) {
				collision_num++;
				colliding_subjs.push(colliding_subj);
			}	
		}

		if (collision_num > 0) {
			document.getElementById("pre_conf").innerHTML += "<p><strong>The following subject(s)/class(es) have already been assigned to other teachers</strong>: " + colliding_subjs.join(", ") + ". Though this is not an error, it can create problems later.";		
		}

		subj_collisions = [];

		var table = "";
		table += '<p><em>Clicking confirm will add the following teacher to the system:</em><p><table border="1" cellspacing="5%"><thead><th>Teacher Name<th>Subjects/Classes Taught</thead><tbody><tr><td>' + name;	
 
		var selection =	"";

		for (var subj in selected_subjs) {
			if ( selected_subjs[subj] ) {
				var classes = selected_subjs[subj];
				var combi = subj + "(" + classes.join(", ") + ")<br>";
				selection += combi;
			}
		}

		table += "<td>" + selection;
		table += "</tbody></table>";

		document.getElementById("pre_conf").innerHTML += table;

		var form = '<form action="/cgi-bin/editteacherlist.cgi" method="POST">';

		form += '<INPUT type="hidden" name="confirm_code" value="$conf_code">';
		form += '<INPUT type="hidden" name="teacher_name" value="' + name + '">';

		for (var subj in selected_subjs) {
			if ( selected_subjs[subj] ) {
				var classes = selected_subjs[subj];
				var classes_joined = classes.join(",");
				form += '<INPUT type="hidden" name="subject_' + subj + '" value="' + classes_joined + '">';	
			}
		}

		selected_subjs = [];

		if (ta_edited >= 0) {
			form += '<INPUT type="hidden" name="teacher_id" value="' + ta_edited + '">';
		}
		
		form += '<INPUT type="submit" name="save" value="Save">&nbsp;&nbsp;<INPUT type="button" name="cancel_changes" value="Cancel" onclick="cancel()"></form>';
	
		document.getElementById("pre_conf").innerHTML += '<p>' + form; 
	}

	function cancel() {
		document.getElementById("pre_conf").style.border = "";
		document.getElementById("pre_conf").style.width = "";	
		document.getElementById("pre_conf").style.padding = "";	

		ta_edited = -1;

		selected_subjs = [];
		selected_teachers = [];
		subj_collisions = [];

		document.getElementById("pre_conf").innerHTML = old_content;
	}

	function del() {
		if (selected_teachers.length > 0) {
			document.getElementById("pre_conf").style.border = "2px solid black";
			document.getElementById("pre_conf").style.width = "600px";	
			document.getElementById("pre_conf").style.padding = "2%";	
		
			old_content = document.getElementById("pre_conf").innerHTML;

			document.getElementById("pre_conf").innerHTML = "";

			var plural = "teacher";
			if (selected_teachers.length > 1) {
				plural = "teachers";
			}
			var new_content = "Are you sure you want to <strong>permanently</strong> delete the following " +  plural + "?"
			new_content += '<p><TABLE cellpadding="5%" border="1"><THEAD><TH>Staff ID<TH>Name<TH>Subjects Taught</THEAD><TBODY>';

			for (var i = 0; i < selected_teachers.length; i++) {
				var id = selected_teachers[i];
				var name = "";
				var subjects = "";

				for (var ta in all_tas) {
					if (all_tas[ta].id == selected_teachers[i]) {
						name = all_tas[ta].name;
						var unformed_subjects = all_tas[ta].subjects.split(";");
						subjects = unformed_subjects.join("<br>");
						break;
					}
				}
				new_content += "<TR><TD>" + id + "<TD>" + name + "<TD>" + subjects;
			}
			new_content += "</TBODY></TABLE>";
			
			var del_list = selected_teachers.join(",");

			selected_teachers = [];

			new_content += '<p><FORM action="/cgi-bin/editteacherlist.cgi" method="POST">';

			new_content += '<INPUT type="hidden" name="confirm_code" value="$conf_code">';
			new_content += '<INPUT type="hidden" name="delete_list" value="' + del_list + '">';
			new_content += '<INPUT type="submit" name="delete" value="Delete">&nbsp;&nbsp;<INPUT type="button" name="cancel_changes" value="Cancel" onclick="cancel()"></form>';
		
			document.getElementById("pre_conf").innerHTML = new_content;
		}
	}

	function edit() {
		document.getElementById("pre_conf").style.border = "2px solid black";
		document.getElementById("pre_conf").style.width = "600px";	
		document.getElementById("pre_conf").style.padding = "2%";	
		
		old_content = document.getElementById("pre_conf").innerHTML;

		document.getElementById("pre_conf").innerHTML = "";

		var selected_id = selected_teachers[0];
		ta_edited = selected_id;

		selected_teachers = [];

		var selected_ta_name = "";
		var selected_subjects_str = "";

		for (var ta_iter in all_tas) {
			if (all_tas[ta_iter].id == selected_id) {
				selected_ta_name = all_tas[ta_iter].name;
				selected_subjects_str = all_tas[ta_iter].subjects;
				break;
			}
		}


		var subject_class_arr = selected_subjects_str.split(";");
		
		var subject_class_hash = new Array();
	
		var re = /^([^\\u0028]+)\\u0028([^\\u0029]+)\\u0029\$/;
	
		for (var j = 0; j < subject_class_arr.length; j++) {	
			var classes_matched = re.exec(subject_class_arr[j]);	
			if (classes_matched) {
				var subj = classes_matched[1];
				var class_names = classes_matched[2];
	
				subject_class_hash[subj] = [];
	
				var classes_list = class_names.split(", ");
	
				subject_class_hash[subj] = classes_list;	
			}
		}

		var new_content = '<div id="name_collision_msg"></div><div style="color: red" id="subject_collision_msg"></div><TABLE cellspacing="10%">';
		
		new_content += '<TR><TD><span id="name_collision_asterisk" style="color: red"></span><LABEL for="ta_name" style="font-weight: bold">Teacher\\'s&nbsp;Name: </LABEL><TD><INPUT type="text" name="ta_name" id="ta_name" size="40" maxlength="80" value="' + selected_ta_name + '" onblur="check_name_collision()">';

		//new_content += "</TABLE><TABLE>";
		for (var j = 0; j < subjects.length; j++) {

			var attached_classes = [];

			if (subject_class_hash[subjects[j]]) {	
				attached_classes = subject_class_hash[subjects[j]];
			}

			new_content += '<TR><TD><span style="color: red" id="' + subjects[j] + '_asterisk"></span><LABEL style="font-weight: bold">' + subjects[j] + '</LABEL><TD><DIV style="height: 50px; border: 1px solid black; overflow-y: scroll">';

			var any_year = "Any Year"
			for (var i = 0; i < classes.length; i++) {
				var elem_id = subjects[j] + "_" + classes[i];
				var checked = "";

				for (var k = 0; k < attached_classes.length; k++) {
					if (attached_classes[k].toLowerCase() == classes[i].toLowerCase()) {
						checked = " checked";

						if ( !selected_subjs[subjects[j]] ) {
							selected_subjs[subjects[j]] = [];
						}

						selected_subjs[subjects[j]].push(classes[i]);
					}
				}
 	
				new_content += '<INPUT type="checkbox"' + checked + ' onclick=\\'add_new_subj_class("' + subjects[j] + '", "' + classes[i]+ '")\\' id="' + elem_id + '"><label>' + classes[i] + '</label>&nbsp;  ';
			}
			new_content += '</DIV>';
		}

		new_content += '<tr><td><INPUT type="button" name="save" value="Save" onclick="save()"><td><INPUT type="button" name="cancel" value="Cancel" onclick="cancel()">';

		document.getElementById("pre_conf").innerHTML = new_content;
	}

</SCRIPT>
</head>
<body>
$header
<hr><div id="pre_conf"> 
$per_page_guide 
$sort_guide
$search_bar
<p><em><span id="add_teacher_feedback">$add_teacher_feedback</span></em>
<p><input type="button" name="add_new_teacher" value="Add New Teacher" onclick="add_new_teacher()">
$tas_table
<p><input disabled type="button" name="delete" id="delete" value="Delete Selected" onclick="del()">&nbsp;&nbsp;<input disabled type="button" name="edit" id="edit" value="Edit Selected" onclick="edit()">
*;

if ($cntr > 10) {
	$content .= "<br>$search_bar";
}

$content .= 
qq*
$page_guide
</div>
</body>
</html>
*;

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

