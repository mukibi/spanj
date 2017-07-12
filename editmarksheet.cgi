#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d);
my %session;
my $logd_in = 0;
my $id;
my $full_user = 0;

my ($marksheet,$act,$formula) = (undef, undef, undef);
my @em_classes = ();
my $update_session = 0;
my $conf_code;
my ($arithm_expr_error, $load_input_error) = (undef, undef);
my %all_adms = ();
 
if ( exists $ENV{"QUERY_STRING"} ) {
	if ( $ENV{"QUERY_STRING"} =~ /\&?marksheet=([^\&]+)\&?/ ) {	
		$marksheet = $1;
	}
	if ( $ENV{"QUERY_STRING"} =~ /\&?act=([^\&]+)\&?/ ) {	
		$act = $1;
	}	
}

my $spc = " ";
if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;
	for my $unprocd_tuple (@session_data) {
		$unprocd_tuple =~ s/\+/$spc/ge;
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
		$id = $session{"id"};
		#privileges set
		if (exists $session{"privileges"}) {
			my $priv_str = $session{"privileges"};	
			my $spc = " ";
			$priv_str =~ s/\+/$spc/g;
			$priv_str =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			if ($priv_str eq "all") { 
				$logd_in++;
				$full_user++;
			}
			else {
				if (exists $session{"token_expiry"} and $session{"token_expiry"} =~ /^\d+$/) {
					if ($session{"token_expiry"} > time) {
						$logd_in++;
						my @privs = split/,/,$priv_str;
						my $cntr = 0;
						foreach (@privs) {	
							if ($_ =~ m!^EM\(([^\)]+)\)$!) {	
								push @em_classes, $1;	
							}
						}
					}
				}
			}
		}
	}
}

unless ($logd_in) {
	print "Status: 302 Moved Temporarily\r\n";
	print "Location: /login.html?cont=/cgi-bin/editroll.cgi\r\n";
	print "Content-Type: text/html; charset=UTF-8\r\n";
   	my $res = 
               	"<html>
               	<head>
		<title>Spanj: Exam Management Information System - Redirect Failed</title>
		</head>
         	<body>
                You should have been redirected to <a href=\"/login.html?cont=/cgi-bin/editroll.cgi\">/login.html?cont=/cgi-bin/editroll.cgi</a>. If you were not, <a href=\"/cgi-bin/editroll.cgi\">Click Here</a> 
		</body>
                </html>";

	my $content_len = length($res);	
	print "Content-Length: $content_len\r\n";
	print "\r\n";
	print $res;
	exit 0;
}

my $post_mode = 0;
my %auth_params;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	$post_mode++;
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
}

my %all_marksheets;
my $con;
my $marks_range = "0-100";

if (@em_classes or $full_user) {
	#simply loads the entire marksheets table to memory	

	$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});	

	if ($con) {

		#read permitted range of input mark
		#the 2 SELECTs can probably be replaced by a neat INNER JOIN
		my $prep_stmt = $con->prepare("SELECT table_name,roll,exam_name,subject,time FROM marksheets");
		if ($prep_stmt) {
			my $rc = $prep_stmt->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt->fetchrow_array()) {
					$all_marksheets{$rslts[0]} = {"roll" => $rslts[1], "exam_name" => $rslts[2], "subject" => $rslts[3], "time" => $rslts[4]};
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM marksheets: ", $prep_stmt->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM marksheets: ", $prep_stmt->errstr, $/;  
		}
		my $current_yr = (localtime)[5] + 1900;

		#the marksheets have different indexes from the student rolls
		#read the student_rolls table to lookup the 'roll' ref'd in
		#marksheets
		my $prep_stmt2 = $con->prepare("SELECT table_name,class,start_year FROM student_rolls");
		if ($prep_stmt2) {
			my $rc = $prep_stmt2->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt2->fetchrow_array()) {
					my ($roll,$class,$start_year) = @rslts;
					#my $class_yr = ($current_yr - $start_year) + 1;
					#$class =~ s/\d+/$class_yr/;
					MARKSHEET: foreach (keys %all_marksheets) {
						if (${$all_marksheets{$_}}{"roll"} eq $roll) {
							#add a 'class' key to the 'marksheets' hashtable
							#assume an exam year that is the current year
							my $exam_yr = $current_yr;
							#every exam should hav a 4-digit year
							#use this year as the exam year
							if (${$all_marksheets{$_}}{"exam_name"} =~ /(\d{4,})/) {
								$exam_yr = $1;	
							}

							if ($exam_yr < $start_year) {
								delete $all_marksheets{$_};
								next;
							}
							my $class_yr = ($exam_yr - $start_year) + 1;
							my $edited_class = $class;

							$edited_class =~ s/\d+/$class_yr/;

 							
							${$all_marksheets{$_}}{"class"} = $edited_class;	
						}
					}
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM student_rolls: ", $prep_stmt2->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM student_rolls: ", $prep_stmt2->errstr, $/;  
		}

	}
	else {
		print STDERR "Cannot connect: $con->strerr$/";
	}
}

my %authd_marksheets;

#full
if ($full_user) {
	%authd_marksheets = %all_marksheets;
}
else {
	for my $class_subject (@em_classes) {		 
		ALL_MARKS: foreach (keys %all_marksheets) {
			my $k_vs = $all_marksheets{$_};
			#do a case-insensitive string cmp
			#may need to review a lot of code
			#to ensure the rest of this project is
			#case insensitive.
			if ( lc($class_subject) =~ /^${$k_vs}{"class"}\s/i and  lc($class_subject) =~ /\s${$k_vs}{"subject"}$/i) {
				$authd_marksheets{$_} = $k_vs;	
			}
		}
	}
}

my $content = 
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Edit Marksheet</title>
};

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/editmarksheet.cgi">Edit Marksheet</a>
	<hr> 
};

my $num_authd = scalar(keys %authd_marksheets);

if ($num_authd > 0)  {
	#user has made some changes to the marksheet 
	if ($post_mode) {	
		if (exists $authd_marksheets{$marksheet}) {
			if (exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $auth_params{"confirm_code"} eq $session{"confirm_code"}) {

				my $min_mark = 0;
				my $max_mark = 100;

				my $prep_stmt9 = $con->prepare( "SELECT value FROM vars WHERE id='1-marks range' LIMIT 1" );

				if ($prep_stmt9) {

					my $rc = $prep_stmt9->execute();

					if ($rc) {
						while ( my @rslts = $prep_stmt9->fetchrow_array() ) {

							if ( $rslts[0] =~ /^([0-9]+)\-([0-9]+)/ ) {

								$min_mark = $1;
								$max_mark = $2;
								$marks_range = $rslts[0];

								#reversed values
								if ( $min_mark > $max_mark ) {
									my $tmp = $max_mark;
									$max_mark = $min_mark;
									$min_mark = $tmp;
									$marks_range = "$min_mark-$max_mark";
								}
							}
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM vars: ", $prep_stmt9->errstr, $/;
					}

				}
				else {
					print STDERR "Could not prepare SELECT FROM vars: ", $prep_stmt9->errstr, $/;  
				}

				my %errors;
				my @to_update;
				my $update_cntr = 0;
				if (defined $act and $act eq "load") {
					

					my ($marksheet_subject, $marksheet_roll) = (lc(${$authd_marksheets{$marksheet}}{"subject"}), ${$authd_marksheets{$marksheet}}{"roll"});

					
					if (exists $auth_params{"formula"}) {

						my $formula = lc($auth_params{"formula"});
						my @seen_marksheets = ();

 						for my $marksheet_2 (keys %authd_marksheets) {

							my $name_of_exam = lc(${$authd_marksheets{$marksheet_2}}{"exam_name"});
							#must be same class
							next if (${$authd_marksheets{$marksheet_2}}{"roll"} ne  $marksheet_roll);
							#and same subject
							next if (lc(${$authd_marksheets{$marksheet_2}}{"subject"}) ne $marksheet_subject);
			
							my $exam_index = index( $formula, $name_of_exam );
							if ( $exam_index >= 0 ) {
								my $n_formula = substr($formula, 0, $exam_index) . $marksheet_2 . substr($formula, $exam_index + length($name_of_exam));
								$formula = $n_formula;	
								push @seen_marksheets, $marksheet_2;	
							}
						}
						#formula should now be an arithmetic expression
						my %records = ();
						my $lim = 0;
 						my $prep_stmt7 = $con->prepare("SELECT adm,subjects FROM `$marksheet_roll`");
						if ($prep_stmt7) {
							my $rc = $prep_stmt7->execute();
							if ($rc) {
								while (my @rslts = $prep_stmt7->fetchrow_array()) {
									my $adm = $rslts[0];
									my @subjs = split/,/,lc($rslts[1]);
									foreach (@subjs) {
										if ($_ eq $marksheet_subject) {
											$records{$adm} = $formula;	
											$lim++;
											last;
										}
									}
								}
							}
							else {
								print STDERR "Could not execute SELECT FROM $marksheet_roll: ", $prep_stmt7->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare SELECT FROM $marksheet_roll: ", $prep_stmt7->errstr, $/;  
						}

						for my $seen_marksheet (@seen_marksheets) {
							my $prep_stmt8 = $con->prepare("SELECT adm,marks FROM `$seen_marksheet` LIMIT $lim");

							if ($prep_stmt8) {
								my $rc = $prep_stmt8->execute();
								if ($rc) {
									while (my @rslts = $prep_stmt8->fetchrow_array()) {
										my $adm = $rslts[0];
										my $mark = $rslts[1];
										unless (defined $mark and $mark =~ /^\d+$/) {
											$errors{$adm}++;
											$load_input_error++;
											$mark = 0;
										}	
										my $marksheet_index = index( $records{$adm}, $seen_marksheet );
										if ( $marksheet_index >= 0 ) {
											my $n_formula = substr($records{$adm}, 0, $marksheet_index) . $mark . substr($records{$adm}, $marksheet_index + length($seen_marksheet));
											$records{$adm} = $n_formula;		
										}
									}
								}
								else {
									print STDERR "Could not execute SELECT FROM $marksheet_roll: ", $prep_stmt8->errstr, $/;
								}
							}
							else {
								print STDERR "Could not prepare SELECT FROM $marksheet_roll: ", $prep_stmt8->errstr, $/;  
							}
						}

						for my $stud_adm (keys %records) {	
							#by now this value should be 
							#just spaces, numbers & math ops
							my $val = 0;
							if ($records{$stud_adm} =~ m!^[0-9\.\+\-*\/\s]+$!) {	
								$val = eval $records{$stud_adm};
							}
							else {
								$load_input_error++;
								$errors{$stud_adm}++;
							}
							push @to_update, $stud_adm, $val;
							$update_cntr++;

						}
					}
					else {
						$arithm_expr_error = 1;
					}
				}
				else {
					for my $param (keys %auth_params) {
						if ($param =~ /^marks_(\d+)$/) {
							my $adm = $1;
							my $marks = $auth_params{$param};
							if ($marks =~ /^\d+$/ and $marks >= $min_mark and $marks <= $max_mark) {
								push @to_update,$adm;
								push @to_update,$marks;
								$update_cntr++;
							}
							else {
								$errors{$adm}++;
							}
						}
					}
				}
				if ($update_cntr) {
					if ($con) {
						my @literal_insert_bts = ();

						my @vals_placeholder_bts = ();
						for (my $i = 0; $i < $update_cntr; $i++) {
							push @vals_placeholder_bts, "(?,?)";
							if ($i % 2 == 0) { 
								push @literal_insert_bts, "($to_update[$i], $to_update[$i+1])";
							}
						}
						my $vals_placeholder = join (",", @vals_placeholder_bts);
						my $prep_stmt6 = $con->prepare("REPLACE INTO `$marksheet` VALUES $vals_placeholder");	
						if ($prep_stmt6) {
							my $rc = $prep_stmt6->execute(@to_update);
							if ($rc) {

								my $subject =  ${$authd_marksheets{$marksheet}}{"subject"};
								my $class =  ${$authd_marksheets{$marksheet}}{"class"}; 
								my $exam =  ${$authd_marksheets{$marksheet}}{"exam_name"};

								my @today = localtime;	
								my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

								open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        							if ($log_f) {
									my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
									flock ($log_f, LOCK_EX) or print STDERR "Could not log edit marksheets for $id due to flock error: $!$/"; 
									seek ($log_f, 0, SEEK_END);
									#for ( my $i = 0; $i < @to_update; $i += 2 ) {
										print $log_f "$id EDIT MARKSHEET ($class $exam $subject) $time\n";
									#}
									flock ($log_f, LOCK_UN);
                							close $log_f;
        							}
								else {
									print STDERR "Could not log update marksheet for $id: $!\n";
								}

								#update edit marksheet data to show the last person who edited the table
								my $user_name ="-";
								my $time = time;
								if (exists $session{"name"}) {
									$user_name = $session{"name"};
								}

								my $prep_stmt9 = $con->prepare("REPLACE INTO edit_marksheet_log VALUES(?,?,?)");
								if ($prep_stmt9) {
									my $rc = $prep_stmt9->execute($marksheet, $user_name, $time);
									unless ($rc) {
										print STDERR "Could not execute REPLACE INTO marksheet_edit_log statement: ", $prep_stmt9->errstr, $/;	
									}
								}
								else {
									print STDERR "Could not prepare REPLACE INTO marksheet_edit_log statement: ", $prep_stmt9->errstr, $/;
								}
								$con->commit();
							}
							else {
								print STDERR "Could not execute REPLACE INTO marksheet table: ", $prep_stmt6->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare REPLACE INTO marksheet: ", $prep_stmt6->errstr, $/;
						}
					}
				}
				append_load_js();
				display_for_editing($marksheet, \%errors);
				$content =~ s/dummy_conf_code/$conf_code/;
				my $all_adms_list_js = join(", ", keys %all_adms);
				$content =~ s/dummy_all_adms_list_js/$all_adms_list_js/;

			}
			else {
				$content .= "</head><body>$header<em>Sorry, your request was not sent with correct authorization tokens.</em> To continue, reload this page.</body></html>";
			}
		}
		else {
			$content .= "</head><body>$header<em>Sorry, you are not authorized to edit this marksheet.</em></body></html>";
		}
		
	}
	else {
		#display marksheet for editing
		if (defined $marksheet) {
			if (exists $authd_marksheets{$marksheet}) {
				append_load_js();
				display_for_editing($marksheet);
				#replace dummy_conf_code
				$content =~ s/dummy_conf_code/$conf_code/;

				my $all_adms_list_js = join(", ", keys %all_adms);
				$content =~ s/dummy_all_adms_list_js/$all_adms_list_js/;
			}
			else {
				$content .= "</head><body>$header<em>Sorry, you are not authorized to edit this marksheet.</em></body></html>";
			}
		}
		#display list of marksheets for user to select from
		else {
			$content .= "</head><body>" . $header;
			my $pre = "";
			if ($num_authd == 1) {
				$content .= "<p>You are authorized to edit the following marksheet: ";
			}
			else {
				$content .= "<p>You are authorized to edit the following marksheets:<ul>";
				#$pre = "<li>";
			}
		
			
			my %exam_times = ();

			foreach ( keys %authd_marksheets ) {

				my $time = ${$authd_marksheets{$_}}{"time"};
				my @time_bts = localtime($time);
				my $yr =$time_bts[5] + 1900;
			
				${$authd_marksheets{$_}}{"year"} = $yr;

				my $exam = ${$authd_marksheets{$_}}{"exam_name"};

				if ( not exists $exam_times{$exam} ) {
					${$exam_times{$exam}}{"num_exams"} =  0;
					${$exam_times{$exam}}{"total"} =  0;
					${$exam_times{$exam}}{"avg"} =  0;
				}

				${$exam_times{$exam}}{"num_exams"}++;
				${$exam_times{$exam}}{"total"} += $time;
				${$exam_times{$exam}}{"avg"} = ${$exam_times{$exam}}{"total"} / ${$exam_times{$exam}}{"num_exams"};
			}

			my %reorgd_marksheets = ();
			

			my %yr_subjects;

			foreach ( keys %authd_marksheets) {

				my %marksheet = %{$authd_marksheets{$_}};
	
				my $yr = $marksheet{"year"};
				my $exam = $marksheet{"exam_name"};
				my $subject = $marksheet{"subject"};
				my $class = $marksheet{"class"};

				$reorgd_marksheets{$yr}->{$exam}->{$subject}->{$class} = $_; 

				${$yr_subjects{$yr}}{$subject}++;

			}
	
			for my $yr ( sort { $b <=> $a } keys %reorgd_marksheets ) {

				my @yr_subjects = sort { $a cmp $b } keys %{ $yr_subjects{$yr} };
				my $subjs = "";

				for ( my $i = 0; $i < @yr_subjects; $i++ ) {
					$subjs .= "<TD>$yr_subjects[$i]";
				}

				$content .= qq!<h3>$yr</h3><table border="1" cellspacing="5%" cellpading="5%"><TR style="font-weight: bold"><TD>&nbsp;$subjs!;

				for my $exam ( sort { ${$exam_times{$b}}{"avg"} <=> ${$exam_times{$a}}{"avg"} } keys %{$reorgd_marksheets{$yr}} ) {
					$content .= qq!<TR><TD style="font-weight: bold">$exam!;

					
					for ( my $j = 0; $j < @yr_subjects; $j++ ) {
						if ( exists $reorgd_marksheets{$yr}->{$exam}->{$yr_subjects[$j]} ) {
							$content .= "<TD>";
							for my $class ( sort { $a cmp $b } keys %{ $reorgd_marksheets{$yr}->{$exam}->{$yr_subjects[$j]} }) {

								my $marksheet = $reorgd_marksheets{$yr}->{$exam}->{$yr_subjects[$j]}->{$class};
								$content .= qq!<a href="/cgi-bin/editmarksheet.cgi?marksheet=$marksheet">$class</a><BR>!;
							}
						}
						else {
							$content .= "<TD>&nbsp;";
						}
					}
				}

				$content .= "</table>";

			}

			$content  .= "</body></html>";
		}
	}
}
else {
	$content .= "</head><body>$header";
	unless (keys %all_marksheets) {
		$content .= "</em>There are no marksheets created yet.</em>"
	}
	else {
		$content .= "<em>Sorry, you are not authorized to edit any marksheet.</em> To continue, obtain an up-to-date token with the appropriate privileges from the Administrator.";
		$content .= "</body></html>";
	}
}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

if ($update_session) { 
	my @new_sess_array = ();
	for my $sess_key (keys %session) {	
		push @new_sess_array, $sess_key."=".$session{$sess_key};        
	}
	my $new_sess = join ('&',@new_sess_array);
	print "X-Update-Session: $new_sess\r\n";
}

print "\r\n";
print $content;
$con->disconnect() if ($con);


sub marksheet_sort {
        my $class_a = ${$authd_marksheets{$a}}{"class"};
        my $class_b = ${$authd_marksheets{$b}}{"class"};
        
        my $res = lc($class_a) cmp lc($class_b);
        if ($res == 0) {
                my $exam_a =  ${$authd_marksheets{$a}}{"exam_name"};
                my $exam_b =  ${$authd_marksheets{$a}}{"exam_name"};
                $res = lc($exam_a) cmp lc($exam_b);
        }
        return $res; 
}


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

sub display_for_editing {
	
	if (scalar(@_) > 0) {
		my $marksheet_table = $_[0];
		my $feedback = '';

		$conf_code = gen_token();
		$session{"confirm_code"} = $conf_code;
		$update_session++;

		my %errors = ();
		if (scalar(@_) > 1)  {
			%errors = %{$_[1]};
			if (keys %errors) {
				if (defined $arithm_expr_error or defined $load_input_error) {

					if (defined $arithm_expr_error) {
						$feedback .= qq!<p><span style="color: red">Some issues were found with the data you sent.</span> This may be due to entering a formula that is not a valid arithmetic expression.!;
					}

					if (defined $load_input_error) {
						$feedback .= qq!<p><span style="color: red">Some issues were found with the data you sent.</span> One or more of the exams requested for the load operation was not found or some of the data was missing for some students.!;
					}
				}
				else {
					$feedback = qq{<p><span style="color: red">Some issues were found with the data you sent.</span> This may have been caused by leaving fields blank, entering non-numeric values or feeding numbers outside the permitted range ($marks_range).</p>};
				}
			}
		}
		unless ($con) {
			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

		}
		if ($con) {
			my $stud_roll = ${$authd_marksheets{$marksheet_table}}{"roll"};
			my $subject =  ${$authd_marksheets{$marksheet_table}}{"subject"};
			my $class =  ${$authd_marksheets{$marksheet_table}}{"class"}; 
			my $exam =  ${$authd_marksheets{$marksheet_table}}{"exam_name"}; 

			my %studs_in_class;
			my $res_table =	
qq{
<p><h4><span style="text-decoration: underline">$class $exam $subject</span></h4></p>
$feedback

<FORM method="POST" action="/cgi-bin/editmarksheet.cgi?marksheet=$marksheet_table">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<TABLE border="1" cellspacing="5%" style="border: 4px black solid; border-spacing: 3pt">
<THEAD>
<TH>
<TH>Adm No.
<TH>Name
<TH><span id="multi_papers_header"></span>Marks
</THEAD>
<TBODY>
};

			my $prep_stmt5 = $con->prepare("SELECT `${stud_roll}`.adm,`${stud_roll}`.s_name,`${stud_roll}`.o_names,`${stud_roll}`.subjects,`${marksheet_table}`.marks FROM `$stud_roll` LEFT JOIN `$marksheet_table` ON `${stud_roll}`.adm = `${marksheet_table}`.adm ORDER BY `${stud_roll}`.adm");
			my $cntr = 0;
			if ($prep_stmt5) {
				my $rc = $prep_stmt5->execute();
				if ($rc) {

					while (my @rslts = $prep_stmt5->fetchrow_array()) {

						my ($adm,$s_name,$o_names,$subjects,$marks) = @rslts;

						$all_adms{$adm}++;

						$marks = "" unless (defined $marks);
						my %subjects_hash;
						foreach (split/,/,$subjects) {
							$subjects_hash{lc($_)}++;
						}
						if ( exists $subjects_hash{lc($subject)} ) {
							my $err_str = "";
							if (exists $errors{$adm}) {
								$err_str = qq{<SPAN style="color: red">*</SPAN>};
							}
							++$cntr;
							my $name = $s_name . " " . $o_names;
							$res_table .= qq{<TR><TD>$err_str<LABEL for="marks_$adm">$cntr. </LABEL><TD><LABEL for="marks_$adm">$adm</LABEL><TD><LABEL for="marks_$adm">$name</LABEL><TD><span id="multi_papers_box_$adm"></span><INPUT size="4" maxlength="5" type="text" id="marks_$adm" name="marks_$adm" value="$marks">};
						}
					}
					if ($cntr) {
						$res_table .= 
qq{
</TBODY>
</TABLE>
<p><INPUT type="submit" name="save" value="Save Changes">
</FORM>
};					}
					else {
						$res_table = qq{<em>There are no students recorded as taking $subject in $class.</em> If this is not correct, please <a href="/cgi-bin/editroll.cgi?roll=$stud_roll">edit the student roll for this $class</a> to continue. };
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM student_roll statement$/";	
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM student_roll statement$/";
			}
			$content .= $res_table . "</BODY></HTML>";
		}
	}
}

sub append_load_js {

		my ($marksheet_subject, $marksheet_roll) = (lc(${$authd_marksheets{$marksheet}}{"subject"}), ${$authd_marksheets{$marksheet}}{"roll"});

		my $select = qq!<span id="formula_box"><h4>Load Data from Existing Marksheets(<a href="javascript:hide()">Hide</a>)</h4><p><TABLE><TR><TD colspan="2"><LABEL>Which exams would you like to load the data from?</LABEL>!;

		for my $marksheet_2 (sort { ${$authd_marksheets{$a}}{"time"} <=> ${$authd_marksheets{$b}}{"time"} } keys %authd_marksheets) {
			my $name_of_exam = ${$authd_marksheets{$marksheet_2}}{"exam_name"};
			#must be same class
			next if (${$authd_marksheets{$marksheet_2}}{"roll"} ne $marksheet_roll);
			#and same subject
			next if (lc(${$authd_marksheets{$marksheet_2}}{"subject"}) ne $marksheet_subject);

			$select .= qq!<TR><TD><INPUT id="$name_of_exam" type="checkbox" onclick="add(\\'$name_of_exam\\')"><TD>$name_of_exam!;
		}

		$select .= qq!</TABLE><FORM method="POST" action="/cgi-bin/editmarksheet.cgi?marksheet=$marksheet\&act=load"><TABLE><TR><TD><INPUT type="hidden" name="confirm_code" value="dummy_conf_code"><LABEL>Formula</LABEL><TD><INPUT id="formula" name="formula" type="text" size="75" disabled><TR><TD colspan="2"><LABEL><em>e.g. 0.75 * CAT I + 0.25 * CAT II</em></LABEL><TR><TD><INPUT type="submit" name="load" value="Load"><TD>&nbsp;</TABLE></FORM></span>!;
				
		$content .= 
qq!

<SCRIPT type="text/javascript">

var all_adms = [dummy_all_adms_list_js];
var extend = '$select';
var shrink = "<p><h4><a href='javascript:show()'>Load Data from Existing Marksheets</a></h4>";

var selected = [];

var num_papers = 1;

var default_percent_of_total = 100;

var num_re = /^[123]\$/;
var num_re2 = /^[0-9]*(\.[0-9]+)?\$/;

var paper_metadata = [];

function show_multiple_papers() {

	document.getElementById("multi_papers_box").innerHTML = '<p><h4>Enter Multiple Papers</h4><TABLE><TR><TD>How many papers would you like to enter?</TD><TD><span style="color: red" id="number_papers_err"></span><INPUT value="" type="text" id="number_papers" onkeyup="check_num()" onmouseover="check_num()" size="3" maxlength="1"></TD></TR></TABLE><span id="paper_details"></span>';

}


function check_num() {

	var input_number_papers = document.getElementById("number_papers").value;

	if (input_number_papers == num_papers) {
		return;
	}
	if (input_number_papers.match(num_re)) {

		num_papers = input_number_papers;
		default_percent_of_total = 100/num_papers;

		document.getElementById("number_papers_err").innerHTML = "";
	
		if ( num_papers == 1 ) {

			document.getElementById("multi_papers_header").innerHTML = "";
			document.getElementById("paper_details").innerHTML = "";

			for ( var i = 0; i < all_adms.length; i++ ) {
				document.getElementById("multi_papers_box_" + all_adms[i]).innerHTML = '';
				document.getElementById("marks_" + all_adms[i]).readOnly = false;
			}

		}

		else {

			var headers = '';
			var paper_details_content = '<TABLE border="1"><THEAD><TH>Paper<TH>Out of<TH>Percent of Total</THEAD><TBODY>';

			for (var i = 1; i <= num_papers; i++) {

				headers += '&nbsp;Paper ' + i + '&nbsp;</TH><TH>';
				paper_details_content += '<TR><TD>Paper ' + i + '<TD><span style="color: red" id="paper_' + i + '_out_of_err"></span><INPUT type="text" id="paper_' + i + '_out_of" value="100" maxlength="3" size="5" onkeyup="check_paper_metadata()" onmouseover="check_paper_metadata()"><TD><span style="color: red" id="paper_' + i + '_percent_err"></span><INPUT type="text" id="paper_' + i + '_percent" value="' + default_percent_of_total + '" onkeyup="check_paper_metadata()" onmouseover="check_paper_metadata()">';
				
			}

			paper_details_content += '</TBODY>';
			paper_details_content += '<BR><span id="paper_metadata_percent_error" style="color: red"></span>';

			document.getElementById("multi_papers_header").innerHTML = headers;
			document.getElementById("paper_details").innerHTML = paper_details_content;
	
			for ( var i = 0; i < all_adms.length; i++ ) {

				var multi_papers_box_val = '';
				for (var j = 1; j <= num_papers; j++) {
					multi_papers_box_val += '<INPUT type="text" size="7" maxlength="5" id="paper_' + j+ '_marks_' + all_adms[i] + '" onkeyup="update_mark(' + all_adms[i]+ ')" onmouseover="update_mark(' + all_adms[i] + ')">';	
				}

				document.getElementById("multi_papers_box_" + all_adms[i]).innerHTML = multi_papers_box_val;
				document.getElementById("marks_" + all_adms[i]).readOnly = true;
			}
			check_paper_metadata();
		}

	}
	else {
		document.getElementById("number_papers_err").innerHTML = "*";
	}

}

function check_paper_metadata() {

	if (paper_metadata.length > num_papers) {
		paper_metadata.splice(num_papers, paper_metadata.length - num_papers);
	}
	else {
		for (var j = paper_metadata.length; j < num_papers; j++) {
			paper_metadata.push({out_of: 100, percent: default_percent_of_total });
		} 
	}

	var total_percent = 0;

	for (var i = 1; i <= num_papers; i++) {

		var input_out_of = document.getElementById("paper_" + i + "_out_of").value;

		if (input_out_of.match(num_re2)) {
			paper_metadata[i - 1].out_of = input_out_of;
			document.getElementById("paper_" + i + "_out_of_err").innerHTML = "";
		}
		else {
			document.getElementById("paper_" + i + "_out_of_err").innerHTML = "*";
		}

		var input_percent = document.getElementById("paper_" + i + "_percent").value;

		if (input_percent.match(num_re2)) {
			paper_metadata[i - 1].percent = input_percent;
			document.getElementById("paper_" + i + "_percent_err").innerHTML = "";
			total_percent += parseFloat(input_percent);
		}
		else {
			document.getElementById("paper_" + i + "_percent_err").innerHTML = "*";
		}

			
	}

	if (Math.round(total_percent) \!= 100) {	
		document.getElementById("paper_metadata_percent_error").innerHTML = "The 'Percent of Total' column doesn't add up to 100%";
	}
	else {
		document.getElementById("paper_metadata_percent_error").innerHTML = "";
	}
}

function update_mark(adm) {

	var mark = 0;	
	var papers = [];
	for (var i = 1; i <= num_papers; i++) {


		var paper_mark = 0;

		var input_paper_mark = document.getElementById("paper_" + i + "_marks_" + adm).value;

		if ( input_paper_mark.match(num_re2) ) {
			paper_mark = Math.round((input_paper_mark / paper_metadata[i-1].out_of) * paper_metadata[i-1].percent);
		}

		mark += paper_mark;
	}

	document.getElementById("marks_" + adm).value = mark;
}
 
function show() {
	document.getElementById("formula_box").innerHTML = extend;
}

function hide() {
	document.getElementById("formula_box").innerHTML = shrink;
}

function add(exam_name) {
	if (document.getElementById(exam_name).checked) {
		selected.push(exam_name);
	}
	else {
		for (var i = 0; i < selected.length; i++) {
			if (selected[i] === exam_name) {
				selected.splice(i, 1);
				break;
			}
		}
	}
	
	if (selected.length > 0) {
		document.getElementById("formula").disabled = false;
	}
	else {
		document.getElementById("formula").disabled = true;
	}

	if (selected.length > 1) {
		var ratio = 1 / selected.length;
		var txt_bts = [];
		for (var j = 0; j < selected.length; j++) {
			txt_bts.push(ratio.toString() + " * " + selected[j]);
		}
		var txt = txt_bts.join(" + ");
		document.getElementById("formula").value = txt; 
	}
	else {
		document.getElementById("formula").value = exam_name;	
	}
}

</SCRIPT>
!;
		$content .= 
qq!
</HEAD>
<BODY>
$header
<span id="formula_box">
<p>
<h4><a href='javascript:show()'>Load Data from Existing Marksheets</a></h4>
</span>

<span id="multi_papers_box">
<p>
<h4><a href='javascript:show_multiple_papers()'>Enter Multiple Papers</a></h4>
</span>
!;

}

