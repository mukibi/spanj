#!/usr/bin/perl

use strict;
use warnings;

use DBI;
require "./conf.pl";

our($db,$db_user,$db_pwd,$doc_root);
my $con;
my %session = ();
my $query_mode = 0;
my $content = "";
my $search_string = "";
my $encd_search_str = "";

my $page = 1;
my $per_page = 10;

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/search.cgi">Search Database</a>
	<hr> 
};

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
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	if (exists $session{"per_page"} and $session{"per_page"} =~ /^(\d+)$/) {
		$per_page = $1;
	}
}

if ( exists $ENV{"QUERY_STRING"} ) {

	if ( $ENV{"QUERY_STRING"} =~ /\&?pg=(\d+)\&?/ ) {	
		$page = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?q=([^&]+)\&?/ ) {	
		$encd_search_str = $1;
		$search_string = $encd_search_str;
		$search_string =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;	
		if ( length($search_string) > 0 ) {
			$query_mode = 1;
		}
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
		$session{"per_page"} = $per_page;
	}

}

my $row_count = 0;
my $total_rows = 0;
 
my $per_page_guide = "";
my $page_guide = "";

my $res_pages = 0;

#process query params;
#possibly display page-ordered results
#with links for further details
if ($query_mode) {
	my $search_results = "<em>Sorry, your search did not match any student in the database</em>";

	my (%q_adms, %q_names);
	my ($check_adm,$check_name) = (0,0);

	foreach ( split/,/, $search_string ) {
		#assume number is an adm--reasonable
		#assumption but perhaps Native American
		#names like Two-Faced Kangaroo may surprise
		#me
		if ($_ =~ /^\d+$/) {
			$q_adms{$_}++;
			$check_adm++;
		}
		else {
			$q_names{"%" . lc($_) . "%"}++;
			$check_name++;
		}	
	}

	$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
	my %results = ();	
	my %tables = ();

	my $house_label = "House/Dorm";
	if ($con) {

		my $prep_stmt = $con->prepare("SELECT value FROM vars WHERE id='1-house label' LIMIT 1");

		if ($prep_stmt) {

			my $rc = $prep_stmt->execute();

			if ($rc) {

				while (my @rslts = $prep_stmt->fetchrow_array()) {
					if ( defined $rslts[0] ) {
						$house_label = htmlspecialchars($rslts[0]);
					}
				}

			}
			else {
				print STDERR "Couldn't execute SELECT FROM vars: ", $prep_stmt->errstr, $/;
			}
		}
		else {
			print STDERR "Couldn't prepare SELECT FROM vars: ", $prep_stmt->errstr, $/;
		}

	}
	#a bare check_adm need not traverse all
	#tables in the DB it can be satisfied
	#by looking at the 'adms' table;
	if ($check_adm and not $check_name) {

		my $start = $per_page * ($page - 1);
		my $stop = $start + $per_page;

		my @adms_list = ();
		for my $adm (keys %q_adms) {
			push @adms_list, "adm_no=?";
		}
		my $adm_qry = join(' OR ', @adms_list);

		if ($con) {
			my $prep_stmt0 = $con->prepare("SELECT adm_no,table_name FROM adms WHERE $adm_qry ORDER BY adm_no DESC");
			if ($prep_stmt0) {
				my $rc = $prep_stmt0->execute(keys %q_adms);
				if ($rc) {
					my $cntr = 0;
					while ( my @rslts = $prep_stmt0->fetchrow_array() ) {
						$cntr++;
						if ($cntr > $start and $cntr <= $stop) { 
							$results{$rslts[0]} = {"table" => $rslts[1]};	
							$row_count++;
						}
						$total_rows++;
					}
				}
				else {
					print STDERR "Couldn't execute SELECT FROM adms: ", $prep_stmt0->errstr, $/;
				}
			}
			else {
				print STDERR "Couldn't prepare SELECT FROM adms: ", $prep_stmt0->errstr, $/;
			}
		}
	}

	#a name search must scan all tables in the DB
	#an adm search must obtain metadata
	if ($row_count or $check_name) {
		if ($con) {
			#thinking abt how to handle graduate students
			#just display class (class of <graduation year>)
			my $current_year = (localtime)[5] + 1900;	
			my $prep_stmt1 = $con->prepare("SELECT table_name,class,start_year,grad_year FROM student_rolls");
			if ($prep_stmt1) {
				my $rc = $prep_stmt1->execute();
				if ($rc) {
					while ( my @rslts = $prep_stmt1->fetchrow_array() ) {
						#still a student
						if ($current_year <= $rslts[3]) {	
							my $class_year = 1 + ($current_year - $rslts[2]);
							$rslts[1] =~ s/\d+/$class_year/;
						}
						#graduated
						else {
							my $last_class = 1 + ($rslts[3] - $rslts[2]);
							$rslts[1] =~ s/\d+/$last_class/;
							$rslts[1] .= "(Class of $rslts[3])";
						}
						$tables{$rslts[0]} = { "class" => $rslts[1], "start_year" => $rslts[2], "grad_year" => $rslts[3] };
					}
				}
				else {
					print STDERR "Couldn't execute SELECT FROM student_rolls: ", $prep_stmt1->errstr, $/;
				}
			}
			else {
				print STDERR "Couldn't prepare SELECT FROM student_rolls: ", $prep_stmt1->errstr, $/;
			}
		}		
	}

	#Just scanning tables for identified adm(s) 
	if ($row_count and not $check_name) {
		my %tables_to_scan = ();
		for my $adm_no (keys %results) {
			my $table_name = ${$results{$adm_no}}{"table"};
			if (not exists $tables_to_scan{$table_name}) {
				 $tables_to_scan{$table_name} = [$adm_no];
			}
			else {
				push @{$tables_to_scan{$table_name}}, $adm_no;
			}
		}
		for my $table_to_scan (keys %tables_to_scan) {
			my @adms = @{$tables_to_scan{$table_to_scan}};

			my @where_clause_bts = ();
			foreach (@adms) {
				push @where_clause_bts, "adm=?";
			}

			my $where_clause = join(" OR ", @where_clause_bts);

			my $prep_stmt2 = $con->prepare("SELECT adm,s_name,o_names,has_picture,house_dorm FROM `$table_to_scan` WHERE $where_clause");
			if ($prep_stmt2) {
				my $rc = $prep_stmt2->execute(@adms);
				if ($rc) {
					while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
						#save data to results
						${$results{$rslts[0]}}{"name"} = $rslts[1] . " " . $rslts[2];
						${$results{$rslts[0]}}{"picture"} = 0;
						if ($rslts[3] eq "yes") {
							${$results{$rslts[0]}}{"picture"} = 1;
						}
						unless (not defined $rslts[4] or $rslts[4] eq "") {
							${$results{$rslts[0]}}{"house_dorm"} = $rslts[4];
						}
					}
				}
				else {
					print STDERR "Couldn't execute SELECT FROM $table_to_scan: ", $prep_stmt2->errstr, $/;
				}
			}
			else {
				print STDERR "Couldn't prepare SELECT FROM $table_to_scan: ", $prep_stmt2->errstr, $/;	
			}
		}
	}

	#check_name
	#scan all 
	if ($check_name) {
		my $where_clause = "";
		my @where_clause_bts = ();
		#name check
		for my $name (keys %q_names) {
			push @where_clause_bts, "s_name LIKE ?";
			push @where_clause_bts, "o_names LIKE ?";
		}
		for my $adm (keys %q_adms) {
			push @where_clause_bts, "adm=?";
		}
		$where_clause = join(" OR ", @where_clause_bts);

		my @query_params = ();
		push @query_params, keys %q_names;
		push @query_params, keys %q_names;
		push @query_params, keys %q_adms;

		#go over every table
		for my $table (keys %tables) {
			my $prep_stmt3 = $con->prepare("SELECT adm,s_name,o_names,has_picture,house_dorm FROM `$table` WHERE $where_clause");

			if ($prep_stmt3) {
				my $rc = $prep_stmt3->execute(@query_params);
				if ($rc) {
					while ( my @rslts = $prep_stmt3->fetchrow_array() ) {
						#save data to results
						${$results{$rslts[0]}}{"table"} = $table;
						${$results{$rslts[0]}}{"name"} = $rslts[1] . " " . $rslts[2];
						${$results{$rslts[0]}}{"picture"} = 0;
						if (defined $rslts[3] and $rslts[3] eq "yes") {
							${$results{$rslts[0]}}{"picture"} = 1;
						}
						unless (not defined $rslts[4] or $rslts[4] eq "") {
							${$results{$rslts[0]}}{"house_dorm"} = $rslts[4];
						}
						$total_rows++;
					}
				}
				else {
					print STDERR "Can't execute SELECT FROM $table: ", $prep_stmt3->errstr, $/;
				}
			}
			else {
				print STDERR "Couldn't prepare SELECT FROM $table: ", $prep_stmt3->errstr, $/;	
			}
		}

		#cull the recs I don't need

		my $start = $per_page * ($page - 1);
		my $stop = $start + $per_page;

		my @valid_results = ();
		my $cntr = 0;
		for my $stud_adm (sort {$b <=> $a} keys %results) {	
			$cntr++;
			unless ($cntr > $start and $cntr <= $stop) {	
				delete $results{$stud_adm};
			}
			else {
				$row_count++;
			}
		}
	}

	my %images = ();

	opendir (my $images_dir, "${doc_root}/images/mugshots/") or print STDERR "Can't opendir(): $!$/";
	my @files = readdir($images_dir) or print STDERR "Can't readdir(): $!$/";

	for my $file (@files) {
		if ( $file =~ /^(\d+)\./ ) {
			$images{$1} = "/images/mugshots/$file";
		}
	}

	if ($row_count) {
		$search_results = "";
		my $cntr = (($page-1) * $per_page) + 1;
		for my $stud_adm (sort {$b <=> $a} keys %results) {
			my $has_pict = 0;

			my $class = ${ $tables{${$results{$stud_adm}}{"table"}} }{"class"};
			$search_results .= "<p><TABLE>";
			my $rowspan = 5;
			if ( exists ${$results{$stud_adm}}{"house_dorm"} ) {
				$rowspan++;
			}

			if ( ${$results{$stud_adm}}{"picture"} ) {
				if ( exists $images{$stud_adm} ) {
					$has_pict++;
					$rowspan++;
				}
			}
			if ($total_rows > 1) {
				$rowspan++;
				$search_results .= qq!<tr><td rowspan="$rowspan">$cntr&nbsp;&nbsp;</td>!;
			}
			
			if ($has_pict) {
				#ensure proportionate 
				use Image::Magick;
				my $magick = Image::Magick->new;

				my ($width, $height, $size, $format) = $magick->Ping("${doc_root}$images{$stud_adm}");	
				
				my $scale = 1;	
				if ($width > 120 or $height > 150) {
					my $width_scale = 120/$width;
					my $height_scale = 150/$height;

					$scale = $width_scale < $height_scale ? $width_scale : $height_scale;
				}	

				my $h = $height * $scale;
				my $w = $width * $scale;
				$search_results .= qq!<tr><td rowspan="$rowspan"><a href="$images{$stud_adm}"><img height="$h" width="$w" src="$images{$stud_adm}"></a>!;
			}

			$search_results .= qq!<tr><td><span style="font-weight: bold">Adm No.: </span>$stud_adm!;
			$search_results .= qq!<tr><td><span style="font-weight: bold">Name: </span>${$results{$stud_adm}}{"name"}!;
			$search_results .= qq!<tr><td><span style="font-weight: bold">Class: </span>$class!;

			if ( exists ${$results{$stud_adm}}{"house_dorm"} ) {
				$search_results .= qq!<tr><td><span style="font-weight: bold">$house_label: </span>${$results{$stud_adm}}{"house_dorm"}!;
			}
			$search_results .= qq!<tr><td><a href="/cgi-bin/viewresults.cgi?adm=$stud_adm">View results</a>!;
			$search_results .= "</TABLE>";
			$cntr++;
		}
	}

	if ($total_rows > 10) {

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
				$per_page_guide .= " <a href='/cgi-bin/search.cgi?q=$encd_search_str&pg=$re_ordered_page&per_page=$row_cnt'>$row_cnt</a>";
			}
		}
		$per_page_guide .= "</span><hr>";

	}

	$res_pages = $total_rows / $per_page;
	if ($res_pages > 1) {
		if (int($res_pages) < $res_pages) {
			$res_pages = int($res_pages) + 1;
		}
	}

	if ($res_pages > 1) {
		$page_guide .= '<table cellspacing="50%"><tr>';

		if ($page > 1) {
			$page_guide .= "<td><a href='/cgi-bin/search.cgi?q=$encd_search_str&pg=".($page - 1) ."'>Prev</a>";
		}

		if ($page < 10) {
			for (my $i = 1; $i <= $res_pages and $i < 11; $i++) {
				if ($i == $page) {
					$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
				}
				else {
					$page_guide .= "<td><a href='/cgi-bin/search.cgi?q=$encd_search_str&pg=$i'>$i</a>";
				}
			}
		}
		else {
			for (my $i = $page - 4; $i <= $res_pages and $i < ($page + 4); $i++) {
				if ($i == $page) {
					$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
				}
				else {
					$page_guide .= "<td><a href='/cgi-bin/search.cgi?q=$encd_search_str&pg=$i'>$i</a>";
				}
			}
		}
		if ($page < $res_pages) {
			$page_guide .= "<td><a href='/cgi-bin/search.cgi?q=$encd_search_str&pg=".($page + 1)."'>Next</a>";
		}
		$page_guide .= '</table>';
	}
	$content =
qq*
<!DOCTYPE html>
<HTML lang="en">
<META http-equiv="Content-Type" content="text/html; charset=ISO-8859-1">
<HEAD>
<TITLE>Spanj :: Exam Management Information System :: Search Database</TITLE>
</HEAD>
<BODY>
$header
$per_page_guide
$search_results
$page_guide
</BODY>
</HTML>
*;

}

else {
	$content =
qq*
<!DOCTYPE html>
<HTML lang="en">
<META http-equiv="Content-Type" content="text/html; charset=ISO-8859-1">
<HEAD>
<TITLE>Spanj :: Exam Management Information System :: Search Database</TITLE>
</HEAD>
<BODY>
$header
<FORM method="GET" action="/cgi-bin/search.cgi">
<TABLE>
<TR>
<TD><LABEL>Adm No./Name</LABEL>
<TD><INPUT type="text" size="60" title="Search student by adm no. or name" name="q">
<TR><TD><INPUT type="submit" value="Search" title="Click to search">
</TABLE>
</FORM>
</BODY>
</HTML>
*;

}

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
if ($con) {
	$con->disconnect();
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
