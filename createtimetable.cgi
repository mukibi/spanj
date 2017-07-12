#!/usr/bin/perl

use strict;
use warnings;
no warnings 'uninitialized';

use feature "switch";

use DBI;
use Fcntl qw/:flock SEEK_END/;
use Storable qw/freeze thaw/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root);

my %session;
my %auth_params;

my %fixed_scheduling;
my %total_num_associations;

my $logd_in = 0;
my $authd = 0;

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
}

my $content = '';
my $js = '';
my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/yans/">Yans Timetable Builder</a> --&gt; <a href="/cgi-bin/createtimetable.cgi">Create Timetable</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Create Timetable</title>
</head>
<body>
$header
<p><span style="color: red">Sorry, you do not have the appropriate privileges to edit timetable profiles.</span> Only the administrator is authorized to take this action.
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
		print "Location: /login.html?cont=/cgi-bin/createtimetable.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Yans: Timetable Builder - Create Timetable</title>
</head>
<body>
You should have been redirected to <a href="/login.html?cont=/cgi-bin/createtimetable.cgi">/login.html?cont=/cgi-bin/createtimetable.cgi</a>. If you were not, <a href="/login.html?cont=/cgi-bin/createtimetable.cgi">click here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
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
	#processing data sent 
	$post_mode++;
}

my $profile;

if ( exists $ENV{"QUERY_STRING"} ) {

	if ( $ENV{"QUERY_STRING"} =~ /\&?profile=([0-9A-Z]+)\&?/i ) {
		$profile = $1;
	}
}

my %existing_profiles;
$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
#what profiles are there?
if ($con) {
	my $prep_stmt1 = $con->prepare("SELECT table_name, profile_name, creation_time FROM profiles");
	if ($prep_stmt1) {
		my $rc = $prep_stmt1->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt1->fetchrow_array() ) {
				$existing_profiles{$rslts[0]} = {"name" => $rslts[1], "time" => $rslts[2]};
			}
		}
	}
	else {
		print STDERR "Could not create SELECT FROM profiles statement: ", $con->errstr, $/;
	}
}

my $feedback = '';

#use has picked their profile
#they prob want to see sample timetables
#perhaps make manual changes too.

MAKE_TIMETABLE: { 
if ($post_mode) {
	if (exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $session{"confirm_code"} eq $auth_params{"confirm_code"}) {

		#user wants to download and publish the generated timetable
		if (exists $auth_params{"pub_download"}) {
	
			unless ( exists $auth_params{"timetable_conf_code"} ) {
				$feedback = qq!<p><span style="color:red">Invalid timetable selected for Downloading/Publishing.</span>!;
				$post_mode = 0;
				last MAKE_TIMETABLE;
			}

			my $timetable_conf_code = $auth_params{"timetable_conf_code"};
			
			#commit this
			my $prep_stmt10 = $con->prepare("UPDATE timetables SET is_committed=1,published=1 WHERE conf_code=? AND is_committed=0 AND published=0 ORDER BY id DESC LIMIT 1");
			if ($prep_stmt10) {
				my $rc = $prep_stmt10->execute($timetable_conf_code);
				if ($rc) {
					my $rows = $prep_stmt10->rows();
					#did this commit match any record in the database?
					if ($rows == 0) {
						$feedback = qq!<p><span style="color:red">Invalid timetable selected for Downloading/Publishing.</span>!;
						$post_mode = 0;
						last MAKE_TIMETABLE;
					}
				}
			}
			

			#uncommit all others.
			my $prep_stmt11 = $con->prepare("UPDATE timetables SET is_committed=0 WHERE NOT conf_code=?");
			if ($prep_stmt11) {
				$prep_stmt11->execute($timetable_conf_code);
				#@ this very spot sat a silly bug:-
				#it was considered a bug when no timetables had been generated yet.	
			}
		

			#delete all unpublished--cleanup
			my $prep_stmt12 = $con->prepare("DELETE FROM timetables WHERE published=0");
			if ($prep_stmt12) {
				$prep_stmt12->execute();
			}
			$con->commit();

			my ($id,@selected_classes,%selected_days,%exception_days,%day_orgs,%machine_day_orgs,%lesson_assignments,%day_org_num_events,%lesson_to_teachers,%teachers) = (undef,undef,undef,undef,undef,undef,undef,undef,undef,undef);
						
			my $prep_stmt13 = $con->prepare("SELECT id, selected_classes, selected_days, exception_days, day_orgs, machine_day_orgs, lesson_assignments, day_org_num_events, lesson_to_teachers, teachers FROM timetables WHERE is_committed=1 AND published=1 ORDER BY id DESC LIMIT 1");
			if ($prep_stmt13) {
				my $rc = $prep_stmt13->execute();
				if ($rc) {
					while (my @rslts = $prep_stmt13->fetchrow_array()) {

						$id = $rslts[0];

#=pod
						@selected_classes = @{ (thaw($rslts[1])) };
						%selected_days = %{thaw($rslts[2])};
						%exception_days = %{thaw($rslts[3])};
						%day_orgs = %{thaw($rslts[4])};
						%machine_day_orgs = %{thaw($rslts[5])};
						%lesson_assignments = %{thaw($rslts[6])};
						%day_org_num_events = %{thaw($rslts[7])};
						%lesson_to_teachers = %{thaw($rslts[8])};
						%teachers = %{thaw($rslts[9])};
					}
#=cut
				}
			}
		
			unless (defined	$id) {
				$feedback = qq!<span style="color: red">No timetable has been published yet.</span>!;
				$post_mode = 0;
				last MAKE_TIMETABLE;
			}	
	
			#Download 
			use Spreadsheet::WriteExcel;

			my ($workbook,$worksheet,$bold,$default_props,$spreadsheet_name, $row,$col) = (undef,undef,undef,undef,0,0);
			
			$workbook = Spreadsheet::WriteExcel->new("${doc_root}/timetables/$id.xls");

			if (defined $workbook) {

				my $num_cols = 0;
				for my $day_org_1 (keys %day_orgs) {
					if ( $day_org_num_events{$day_org_1} > $num_cols ) {
						$num_cols = $day_org_num_events{$day_org_1};
					}
				}
				my $num_cols_plus_1 = $num_cols + 1;

				$bold = $workbook->add_format( ("bold" => 1) );
				$default_props = $workbook->add_format( () );
				my %merge_props = ("valign" => "vcenter", "align" => "center", "bold" => 1);
				my $merge_format = $workbook->add_format(%merge_props);

				my %merge_props_2 = ("valign" => "vcenter", "align" => "left", "bold" => 0);
				my $merge_format_2 = $workbook->add_format(%merge_props_2);

				$workbook->set_properties( ("title" => "Timetable created \@: " . time, "comments" => "lecxEetirW::teehsdaerpS htiw detaerC; User: 1") );

				for my $class (@selected_classes) {

					my %seen_lessons = ();

					my $prev_org = -1;

					$worksheet = $workbook->add_worksheet($class);
					$worksheet->set_landscape();
					$worksheet->hide_gridlines(0);

#=pod					
					my ($row,$col) = (0,0);
	
					$worksheet->merge_range($row, 0, $row, $num_cols_plus_1 - 1, qq!$class!,$merge_format);

				#$content .= qq!<THEAD><TR><TH colspan="$num_cols_plus_1" style="font-weight: bold; text-align: center; font-size: 1.5em">$class</THEAD>!;

				foreach my $day ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday") {

					next if (not exists $selected_days{$day});

					$row++;
					$col = 0;

					my $organization = 0;	
					my $current_org = 0;

					if (exists $exception_days{$day}) {
						$organization = $exception_days{$day};	
						$current_org = $organization;
					}
	
					#draw table head
					if ($current_org != $prev_org) {
						#$content .= "<THEAD><TH>&nbsp";
						
						$worksheet->write_blank($row,$col++,$default_props);

						my $start_lessons = ${$day_orgs{$current_org}}{"start"};
						my ($hrs,$mins) = (0,0);
						my $colon = "";

						if ($start_lessons =~ /^(\d{1,2})(:?)(\d{1,2})$/) {
							$hrs   = $1;
							$mins  = $3;
							$colon = $2;
						}
	
						my $surplus_cols = scalar(keys %{$machine_day_orgs{$current_org}}) - $num_cols;

						for my $event (sort {$a <=> $b} keys %{$machine_day_orgs{$current_org}}) {

							my $duration = ${${$machine_day_orgs{$current_org}}{$event}}{"duration"};

							my $duration_mins = $duration % 60;
							my $duration_hrs = int($duration / 60);
							
							my $stop_hrs = $hrs + $duration_hrs; 
							my $stop_mins = $mins + $duration_mins;

							if ($stop_mins >= 60) {
								$stop_mins = $stop_mins - 60;
								$stop_hrs++;
							}
							
						my ($display_hrs,$display_stop_hrs) = ($hrs,$stop_hrs);

						#convert to 12hr clock system
						my $am_pm = "AM";
						if ($display_hrs >= 12) {
							if ($display_hrs > 12) {
								$display_hrs -= 12;
							}

							$am_pm = "PM"; 
						}
						else {
							if ($display_hrs == 0) {
								$display_hrs = 12;
							}	
						}

						if ($display_stop_hrs >= 12) {
							if ($display_stop_hrs > 12) {
								$display_stop_hrs -= 12;
							}
							$am_pm = "PM"; 
						}
						else {
							if ($display_stop_hrs == 0) {
								$display_stop_hrs = 12;
							}	
						}

						($display_hrs,$mins,$display_stop_hrs,$stop_mins) = (sprintf("%02d", $display_hrs), sprintf("%02d", $mins), sprintf("%02d", $display_stop_hrs), sprintf("%02d", $stop_mins));	

						my $time = "${display_hrs}${colon}${mins}${am_pm} - ${display_stop_hrs}${colon}${stop_mins}${am_pm}";
							
							
							#write time
							if ($surplus_cols-- > 0) {
								$worksheet->merge_range($row, $col++, $row, $col++, $time, $merge_format);
							}
							else {
								$worksheet->write_string($row,$col++, $time, $bold);
							}
							#$content .= qq!<TH${colspan}>$time!;

							$hrs  = $stop_hrs;
							$mins = $stop_mins;
						}
						#$content .= "</THEAD>";
						$row++;
						$col = 0;
					}

					#draw table body
					#$content .= qq!<TBODY><TR><TD style="font-weight: bold">$day!;
					#write day 
					$worksheet->write_string($row, $col++, $day, $bold);

					my $surplus_cols = $num_cols - scalar(keys %{$machine_day_orgs{$current_org}});

					for my $event (sort {$a <=> $b} keys %{$machine_day_orgs{$current_org}}) {
						my $name = "-";
						my @subjs = ();
	
						if ( exists ${${$lesson_assignments{$class}}{$day}}{$event} ) {
							@subjs = keys %{${${$lesson_assignments{$class}}{$day}}{$event}};
							$name = join("\n",@subjs) if (scalar (@subjs) > 0);
						}

						#my $colspan = "";

						#$colspan = qq! colspan="2"! 
	
						if ($surplus_cols-- > 0) {
							#Bold the fixed name events (might be things like 'Lunch')
							if ($machine_day_orgs{$current_org}->{$event}->{"type"} == 1) {
								$worksheet->merge_range($row, $col++, $row, $col++, $name,$merge_format);
								#$content .= qq!<TD${colspan} style="font-weight: bold">$name!;
							}
							else {
								$worksheet->merge_range($row, $col++, $row, $col++, $name,$merge_format_2);
								#add to seen lessons.
								foreach (@subjs) {
									$seen_lessons{lc("$_($class)")} = $_;
								}
								#$content .= qq!<TD${colspan}>$name!;
							}
						}
						else {
							#Bold the fixed name events (might be things like 'Lunch')
							if ($machine_day_orgs{$current_org}->{$event}->{"type"} == 1) {
								$worksheet->write_string($row, $col++, $name, $bold);
								#$content .= qq!<TD${colspan} style="font-weight: bold">$name!;
							}
							else {
								$worksheet->write_string($row, $col++, $name, $default_props);
								#add to seen lessons.
								foreach (@subjs) {
									$seen_lessons{lc("$_($class)")} = $_;
								}
								#$content .= qq!<TD${colspan}>$name!;
							}
						}
					}
					
					$prev_org = $current_org;
				}

				#write teachers
				my $teachers_str_1 = "";
				my $teachers_str_2 = "";

				my $cntr = 0;

				for my $lesson (keys %seen_lessons) {

					my @teachers_ids = @{$lesson_to_teachers{$lesson}};

					if (@teachers_ids) {
						my @teachers_names = ();
						for my $ta_id (@teachers_ids) {
							push @teachers_names, $teachers{$ta_id}->{"name"};	
						}

						my $ta_str = $seen_lessons{$lesson} . ": " . join(", ", @teachers_names);

						if ($cntr++ % 2 == 0) {
							$teachers_str_1 .= $ta_str. "\n";
						}
						else {
							$teachers_str_2 .= $ta_str ."\n";
						}
	
						
						#$teachers_str .= "\n" if ($cntr++ > 0 and $cntr % 2 == 0);
					}
				}

				$row++;
				$worksheet->merge_range($row, 0, $row, $num_cols_plus_1 - 1, "Teachers", $merge_format);

				my $num_merged_rows = int($cntr / 2) + 1;

				my $half_cols_plus_1 = int($num_cols_plus_1 / 2);
								
				$row++;

				$worksheet->merge_range($row, 0, $row + $num_merged_rows, $half_cols_plus_1, $teachers_str_1, $merge_format_2);
				$worksheet->merge_range($row, $half_cols_plus_1 + 1, $row + $num_merged_rows, $num_cols_plus_1 - 1 , $teachers_str_2, $merge_format_2);
#=cut	
				}
			

				$workbook->close();

				print "Status: 302 Moved Temporarily\r\n";
				print "Location: /timetables/$id.xls\r\n";
				print "Content-Type: text/html; charset=UTF-8\r\n";

   				my $res = 
qq{
<html>
<head>
<title>Spanj: Exam Management Information System - Redirect Failed</title>
</head>
<body>
You should have been redirected to <a href="/timetables/$id.xls">/timetables/$id.xls</a>. If you were not, <a href="/timetables/$id.xls">Click here</a> 
</body>
</html>
};

				my $content_len = length($res);	
				print "Content-Length: $content_len\r\n";
				print "\r\n";
				print $res;	
			}

			else {
				print STDERR "Could not create workbook: $!$/";
				$feedback = qq!<span style="color: red">Could not download spreasheet.</span>!;
				last MAKE_TIMETABLE;
			}

			#log action
			my @today = localtime;	
			my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

			open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

       			if ($log_f) {
       				@today = localtime;	
				my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
				flock ($log_f, LOCK_EX) or print STDERR "Could not log publish timetable for 1 due to flock error: $!$/";
				seek ($log_f, 0, SEEK_END);
				 
				print $log_f "1 PUBLISH TIMETABLE $id $time\n";
				flock ($log_f, LOCK_UN);
       				close $log_f;
       			}

			else {
				print STDERR "Could not log view marksheet for 1: $!\n";
			}

			$con->disconnect if ($con);
			exit 0;

			
		}

		elsif (exists $auth_params{"profile"} and exists $existing_profiles{$auth_params{"profile"}}) {

			my %machine_day_orgs = ();

			#save for future refs
			$session{"profile"} = $auth_params{"profile"};
			$profile = $auth_params{"profile"};
		
			my %profile_vals;

			my $prep_stmt5 = $con->prepare("SELECT name,value FROM `$profile`");
			if ($prep_stmt5) {
				my $rc = $prep_stmt5->execute();
				if ($rc) {
					while (my @rslts = $prep_stmt5->fetchrow_array()) {
						$profile_vals{$rslts[0]} = $rslts[1];
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM profile: ", $prep_stmt5->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM profile: ", $prep_stmt5->errstr, $/;
			}

			my $yrs_study = 4;
			my @classes = ("1", "2", "3", "4");
			my @subjects = ("Mathematics", "English", "Kiswahili", "History", "CRE", "Geography", "Physics", "Chemistry", "Biology", "Computers", "Business Studies", "Home Science");
			my %existing_profiles = ();
		
			my $prep_stmt0 = $con->prepare("SELECT id,value FROM vars WHERE id='1-classes' OR id='1-subjects' LIMIT 2");
			if ($prep_stmt0) {
				my $rc = $prep_stmt0->execute();	
				if ($rc) {
					while ( my @valid = $prep_stmt0->fetchrow_array() ) {
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
	
			my @valid_subjects = ();

			for my $subject (@subjects) {
				push @valid_subjects, "(?:$subject)";
			}

			my $valid_subjects_str = join("|", @valid_subjects);

			my @valid_classes = ();

			for my $class (@classes) {
				push @valid_classes, "(?:$class)";
			}

			my $valid_classes_str = join("|", @valid_classes);	

			my $valid_days_str = "(?:Monday)|(?:Tuesday)|(?:Wednesday)|(?:Thursday)|(?:Friday)|(?:Saturday)|(?:Sunday)";

			#essential fields
			my %fuundamendals = 
(
"days_week" => "^(?:$valid_days_str)(?:,(?:$valid_days_str))*\$",
#"add_fixed_scheduling_lessons_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
"subjects" => "(?:$valid_subjects_str)(?:,(?:$valid_subjects_str))*\$",
#"teachers_number_free_mornings" => "^[0-9]+\$",
#"lesson_structure_classes_[0-9]+" => "^(?:$valid_classes_str)(?:,(?:$valid_classes_str))*\$",
#"exception_days_[0-9]+" => "^(?:$valid_days_str)(?:,(?:$valid_days_str))*\$",
#"teachers_number_free_afternoons" => "^[0-9]+\$",
#"add_lesson_associations_occasional_joint_lessons_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
"lesson_structure_struct_[0-9]+" => "^(?:(?:{LESSON})|(?:[^\\[]+\\[[0-9]+\\]))+\$",
"classes" => "^(?:$valid_classes_str)(?:,(?:$valid_classes_str))*\$",
"lesson_structure_subject_[0-9]+" => "(?:$valid_subjects_str)(?:,(?:$valid_subjects_str))*\$",
"day_organization_0" => "^(?:(?:{LESSON})|(?:[^\\[]+\\[[0-9]+\\]))+\$",
#"lesson_associations_simultaneous_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
#"fixed_scheduling_periods_[0-9]+" => "^(?:(?:$valid_days_str)\\([0-9]+(?:,(?:[0-9]+))*\\))(?:;(?:(?:$valid_days_str)\\([0-9]+(?:,(?:[0-9]+))*\\)))*\$",
"lesson_duration" => "^[0-9]+\$",
#"lesson_associations_occasional_joint_format_[0-9]+" => "^(?:[0-9]+x[0-9]+)(?:,(?:[0-9]+x[0-9]))*\$",
#"fixed_scheduling_lessons_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
#note how i allow a minute of 60? Yes, that wasn't accidental--
#here there be leap seconds
"start_lessons_0" => "^[012]?[0-9]:?[0-6][0-9]\$",
#"add_lesson_associations_mut_ex_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
#"lesson_associations_mut_ex_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
#"teachers_maximum_consecutive_lessons" => "^[0-9]+\$",
#"add_lesson_associations_consecutive_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
"teachers" => "^(?:[0-9]+)(?:,(?:[0-9]+))*\$"
#"lesson_associations_occasional_joint_lessons_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
#"lesson_associations_consecutive_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$",
#"add_lesson_associations_simultaneous_[0-9]+" => "^(?:$valid_lessons_str)(?:,(?:$valid_lessons_str))*\$"
);	
			my %unset_fundamentals;
			FUUNDAS: for my $fuundamendal (keys %fuundamendals) {
				for my $profile_key (keys %profile_vals) {		
					if ($profile_key =~ /$fuundamendal/i) {
						next FUUNDAS;
					}
				}
				$unset_fundamentals{$fuundamendal}++;
			}

			if (scalar(keys %unset_fundamentals) > 0) {
				$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Create Timetable</title>
</head>
<body>
$header
$feedback
<p>The profile selected does not have the following <em>essential values</em> correctly set:<OL>
*;
				for my $unset_fundamental (keys %unset_fundamentals) {
					$content .= "<LI>$unset_fundamental";
				}
				$content .= qq*
</OL>
<p>Would you like to <a href="/cgi-bin/edittimetableprofiles.cgi?profile=$profile">edit this profile</a> and add these essential values? Or do you want to <a href="/cgi-bin/edittimetableprofiles.cgi?act=new">create a new profile</a>? 
</body>
</html>
*;
				last MAKE_TIMETABLE;
			}
			#check day organization time overbudget
			my %day_orgs;
			my $pos;
			for my $profile_name_1 (keys %profile_vals) {
				if ($profile_name_1 =~ /^start_lessons_([0-9]+)/) {	
					$pos = $1;
					if (not exists $day_orgs{$pos}) {
						$day_orgs{$pos} = {};	
					}
					${$day_orgs{$pos}}{"start"} = $profile_vals{$profile_name_1};
				}
				elsif ($profile_name_1 =~ /^day_organization_([0-9]+)/) {
					$pos = $1;	
					if (not exists $day_orgs{$pos}) {
						$day_orgs{$pos} = {};	
					}
					${$day_orgs{$pos}}{"organization"} = $profile_vals{$profile_name_1};
				}
				elsif ($profile_name_1 =~ /^exception_days_([0-9]+)/) {
					$pos = $1;	
					if (not exists $day_orgs{$pos}) {
						$day_orgs{$pos} = {};	
					}
					${$day_orgs{$pos}}{"days"} = $profile_vals{$profile_name_1};
				}	
			}
	
			my %day_org_num_events = ();
			my %day_org_num_lessons = ();

			my $total_weekly_lessons = 0;
			for my $day_org (keys %day_orgs) {

				my $start = ${$day_orgs{$day_org}}{"start"};
				my $day_duration = 1440;

				if ($start =~ /^([0123]*[0-9]):?([0-9][0-9])/) {
					my ($hrs,$mins) = ($1,$2);
					$day_duration -= (($hrs * 60) + $mins);
				}

				my %pre_machine_day_orgs = ();
				my $events_cntr = 0;

				#counts occurences of '{LESSON}'
				my $str = ${$day_orgs{$day_org}}{"organization"};
				my $search_str = "{LESSON}";

				my $num_plain_lessons = 0;
				my $start_index = 0;

				while (1) {
 					my $substr = substr($str, $start_index);
				        my $matched_str = "";
        				my $next_index;

        				if ($substr =~ /($search_str)/i) {
                				$matched_str = $1;
                				$next_index = index($substr, $matched_str) + $start_index;
        				}
        				else {  
                				last;
        				}

        				$num_plain_lessons++;
					$total_weekly_lessons++;
					#I'm using the next_index to identify events at this stage
					#will replace this with an identifier once I've walked over the
					#non-lesson time allocations.
					$pre_machine_day_orgs{$next_index} = {"type" => 0, "duration" => $profile_vals{"lesson_duration"}};

        				$start_index = $next_index + length($matched_str);
        				if ($start_index >= length($str)) {
                				last;
        				}
				}
			
				$day_org_num_lessons{$day_org} = $num_plain_lessons;

				
				$day_duration -= $profile_vals{"lesson_duration"} * $num_plain_lessons;

				$search_str = "([^}]+)\\[([0-9]+)\\]";
 
				my $num_other_time_slices = 0;
				my $other_time_slices = 0;
				$start_index = 0;

				while (1) {
 					my $substr = substr($str, $start_index);
				        my $matched_str = "";
        				my $next_index;

        				if ($substr =~ /($search_str)/) {
                				$matched_str = $1;
						my $event_name = $2;
						my $mins = $3;
			
                				$next_index = index($substr, $matched_str) + $start_index;
						$other_time_slices += $mins;
						$num_other_time_slices++;

						$pre_machine_day_orgs{$next_index} = {"type" => 1, "duration" => $mins, "name"=> $event_name};	
        				}
        				else {  
                				last;
        				}

        				$start_index = $next_index + length($matched_str);
        				if ($start_index >= length($str)) {
                				last;
        				}
				}

				$day_duration -= $other_time_slices;
	
				$day_org_num_events{$day_org} = $num_plain_lessons + $num_other_time_slices;
				
				#time over subscription
				if ($day_duration < 0) {
					$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Create Timetable</title>
</head>
<body>
$header
<p>The 'day organization' of one or more days in this profile assigns more time than is available. This could be due to:
<UL>
<LI>a typo in the 'start of lessons'(e.g. entering a start time of '19:00' when '09:00' is intended)
<LI>an erronous value in square brackets (e.g. typing 'Tea Break[2000]' instead of 'Tea Break[20]')
<LI>the 'duration of lessons' is too large
</UL>
<p>Would you like to <a href="/cgi-bin/edittimetableprofiles.cgi?profile=$profile">edit this profile</a> to fix this issue?
</body>
</html>
*;
					last MAKE_TIMETABLE;
				}

				#harmonize machine day orgs
				my $event_cntr = 0;
				#$machine_day_orgs{$day_org} = {};
				for my $index (sort {$a <=> $b} keys %pre_machine_day_orgs) {
					${$machine_day_orgs{$day_org}}{$event_cntr} = {};
					for my $val ( keys %{$pre_machine_day_orgs{$index}} ) {
						${${$machine_day_orgs{$day_org}}{$event_cntr}}{$val} = ${$pre_machine_day_orgs{$index}}{$val};	
					}
					$event_cntr++;
				}
			}

			my @today = localtime;
			my $current_yr = $today[5] + 1900;

			#check teacher asssignments
			my @selected_tas = split/,/,$profile_vals{"teachers"};
			
			my @where_clause_bts = ();
			foreach (@selected_tas) {
				push @where_clause_bts, "id=?";
			}

			my $where_clause = join(" OR ", @where_clause_bts);

			my %lesson_to_teachers = ();
			my %teachers = ();
			my $prep_stmt6 = $con->prepare("SELECT id,name,subjects FROM teachers WHERE $where_clause");
				
			if ($prep_stmt6) {
				my $rc = $prep_stmt6->execute(@selected_tas);
	
				if ($rc) {
					while (my @valid = $prep_stmt6->fetchrow_array()) {
				
						#say English[1A(2016),2A(2015)];Kiswahili[3A(2014)]
						my $machine_class_subjs = $valid[2];
						my @lessons_taught = ();

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

										#not graduated yet
										if ($grad_yr >= $current_yr) {
											my $class_yr = $yrs_study - ($grad_yr - $current_yr);
											$class_dup =~ s/\d+/$class_yr/;
											push @reformd_classes_list, $class_dup;
										}
									}
								}
								for my $class (@reformd_classes_list) {
									push @lessons_taught, "$subj($class)";
									my $lesson_name = lc("$subj($class)");
									if (not exists $lesson_to_teachers{$lesson_name}) {
										$lesson_to_teachers{$lesson_name} = [];
									}
									push @{$lesson_to_teachers{$lesson_name}},$valid[0];
								}	
							}
						}
						$teachers{$valid[0]} = {"name" => $valid[1], "lessons" => \@lessons_taught};
						
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM teachers statement: ", $prep_stmt6->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM teachers statement: ", $prep_stmt6->errstr, $/;
			}

			my @selected_subjects = split/,/,$profile_vals{"subjects"};
			my @selected_classes =  split/,/,uc($profile_vals{"classes"});

			my %selected_subjects;
			@selected_subjects{@selected_subjects} = @selected_subjects;

			my %selected_classes;
			@selected_classes{@selected_classes} = @selected_classes;
			my %default_lesson_structs;
			my %exceptional_lesson_structs;

			for my $profile_name_4 (keys %profile_vals) {
				if ( $profile_name_4 =~ /^lesson_structure_subject_(\d+)$/ ) {
					my $id = $1;
					my $subject = $profile_vals{"lesson_structure_subject_$id"};

					#only look at selected subjects
					next if ( not exists $selected_subjects{$subject} );

					#is this a valid entry?
					if (exists $profile_vals{"lesson_structure_struct_$id"}) {
						my $struct = $profile_vals{"lesson_structure_struct_$id"};
						#check if this' is an exceptional struct--
						#exception structures hav a '_classes' value.
						if (exists $profile_vals{"lesson_structure_classes_$id"}) {
							my @list_classes = split/,/,$profile_vals{"lesson_structure_classes_$id"};
							foreach (@list_classes) {
								next if (not exists $selected_classes{$_});
								if (not exists $exceptional_lesson_structs{lc($_)}) {
									$exceptional_lesson_structs{lc($_)} = {};
								}
								${$exceptional_lesson_structs{lc($_)}}{$id} = $id;
							}
						}
						else {
							$default_lesson_structs{$subject} = $struct;	
						}
					}
				}
			}

			my %selected_lessons = ();
			CHECK_TEACHERS: {
				my %lesson_struct = ();
			

				for my $selected_subject (@selected_subjects) {

					for my $selected_class (@selected_classes) {

						%lesson_struct = %default_lesson_structs;
						#are there any exceptional lesson structures for this class? 

						if ( exists $exceptional_lesson_structs{lc($selected_class)} ) {

							for my $struct_id (keys %{$exceptional_lesson_structs{lc($selected_class)}}) {

								my $subject = $profile_vals{"lesson_structure_subject_$struct_id"};
								my $struct = $profile_vals{"lesson_structure_struct_$struct_id"};
								if (lc($subject) eq lc($selected_subject)) {
									$lesson_struct{$subject} = $struct;
								}

							}

						}
	
						my @struct = split/,/,$lesson_struct{$selected_subject};

						foreach (@struct) {
							if ($_ =~ /(\d+)x(\d+)/) {

								my $number_lessons     = $1;
								my $periods_per_lesson = $2;
								if ($number_lessons > 0 and $periods_per_lesson > 0) {
									$selected_lessons{lc("$selected_subject($selected_class)")} = "$selected_subject($selected_class)";
								}
							}
						}
					}
				}			
			}
		
				
			for my $lesson (keys %selected_lessons) {
				TA_ITER: for my $ta (keys %teachers) {
					my @tas_lessons = @{${$teachers{$ta}}{"lessons"}};
					for my $tas_lesson (@tas_lessons) {	
						if ( lc($tas_lesson) eq lc($lesson) ) {
							delete $selected_lessons{lc($lesson)};
							next TA_ITER;
						}
					}
				}
			}

			#some classes have not been assigned teachers
			if ( scalar(keys %selected_lessons) > 0 ) {

				my %reformed_lessons = ();

				for my $lesson (keys %selected_lessons) {
					if ($selected_lessons{$lesson} =~ /^([^\(]+)\(([^\)]+)\)$/) {

						my $subject = $1;
						my $classes_str = $2;
						my @classes = split/,/,$classes_str;
					
						if (not exists $reformed_lessons{$subject}) {
							$reformed_lessons{$subject} = [];
						}
						push @{$reformed_lessons{$subject}}, @classes;
					}
				}

	
				$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Create Timetable</title>
</head>
<body>
$header
<P>No teacher has been assigned to teacher the following lessons:
<TABLE border="1">
<THEAD>
<TH>Subject
<TH>Class/es
</THEAD>
<TBODY>
*;
				for my $subject (keys %reformed_lessons) {
					$content .= "<TR><TD>$subject<TD>" . join("&nbsp;&nbsp; ", sort {$a cmp $b} @{$reformed_lessons{$subject}});
				}
				$content .= 
qq*
</TBODY>
</TABLE>
<p>Would you like to <a href="/cgi-bin/edittimetableprofiles.cgi?profile=$profile">edit this profile</a> and select more teachers or do you want to <a href="/cgi-bin/editteacherlist.cgi">edit the list of teachers</a>?
</body></html>";
*;
				last MAKE_TIMETABLE;
			}

			my %exception_days = ();
			my $num_cols = 0;
			for my $day_org_1 (keys %day_orgs) {
				if ( $day_org_num_events{$day_org_1} > $num_cols ) {
					$num_cols = $day_org_num_events{$day_org_1};
				}
				if (exists ${$day_orgs{$day_org_1}}{"days"}) {
					if (exists ${$day_orgs{$day_org_1}}{"organization"}) {
						my @days = split/,/,${$day_orgs{$day_org_1}}{"days"};
						
						foreach (@days) {
							$exception_days{$_} = $day_org_1;
						}
					}
				}
			}

			my @selected_days_list = split/,/, $profile_vals{"days_week"};
			my %selected_days;

			@selected_days{@selected_days_list} = @selected_days_list;

			#to avoid double-assigning a teacher,
			#record all assignements by the day & event
			#count.
			my %teacher_assignments = ();
	
		
		
			my $prev_org = -1;

			#lesson associations
			my %mut_ex_lessons;
			my %simult_lessons;
			my %consecutive_lessons;
			my %occasional_joint_lessons;

			for my $profile_name_6 (keys %profile_vals) {
				#mut ex lessons associations
				if ($profile_name_6 =~ /^lesson_associations_mut_ex_([0-9]+)$/) {

					my @lessons = split/,/,$profile_vals{$profile_name_6};
	
					for ( my $i = 0;$i < @lessons; $i++ ) {

						$total_num_associations{lc($lessons[$i])} += scalar(@lessons);

						my @tas = ();
						if ( exists $lesson_to_teachers{lc($lessons[$i])} ) {
							@tas = @{$lesson_to_teachers{lc($lessons[$i])}}
						}

						for my $ta ( @tas ) {
							my @o_lessons = @{$teachers{$ta}->{"lessons"}};
							for my $o_lesson (@o_lessons) {
								next if ($o_lesson eq $lessons[$i]);
								$total_num_associations{$o_lesson} += (0.5 * scalar(@lessons));	
							}
						}

						if (not exists $mut_ex_lessons{lc($lessons[$i])}) {
							$mut_ex_lessons{lc($lessons[$i])} = {};
						}
						for (my $j = 0; $j < @lessons; $j++) {
							next if ($i == $j);
							${$mut_ex_lessons{lc($lessons[$i])}}{lc($lessons[$j])}++;
						}
					}
				}
				#simultaneous
				elsif ($profile_name_6 =~ /^lesson_associations_simultaneous_([0-9]+)$/) {
					my @lessons = split/,/,$profile_vals{$profile_name_6};
					for ( my $i = 0;$i < @lessons; $i++ ) {

						$total_num_associations{lc($lessons[$i])} += scalar(@lessons);

						my @tas = ();
						if ( exists $lesson_to_teachers{lc($lessons[$i])} ) {
							@tas = @{$lesson_to_teachers{lc($lessons[$i])}}
						}

						for my $ta ( @tas ) {
							my @o_lessons = @{$teachers{$ta}->{"lessons"}};
							for my $o_lesson (@o_lessons) {
								next if ($o_lesson eq $lessons[$i]);
								$total_num_associations{$o_lesson} += (0.5 * scalar(@lessons));	
							}
						}

						if (not exists $simult_lessons{lc($lessons[$i])}) {
							$simult_lessons{lc($lessons[$i])} = {};
						}
						for (my $j = 0; $j < @lessons; $j++) {
							next if ($i == $j);
							${$simult_lessons{lc($lessons[$i])}}{lc($lessons[$j])} = $lessons[$j];
						}
					}
				}
				#consecutive
				elsif ($profile_name_6 =~ /^lesson_associations_consecutive_([0-9]+)$/) {
					my @lessons = split/,/,$profile_vals{$profile_name_6};
					for ( my $i = 0;$i < @lessons; $i++ ) {

						$total_num_associations{lc($lessons[$i])} += scalar(@lessons);
	
						my @tas = ();
						if ( exists $lesson_to_teachers{lc($lessons[$i])} ) {
							@tas = @{$lesson_to_teachers{lc($lessons[$i])}}
						}
						for my $ta ( @tas ) {
							my @o_lessons = @{$teachers{$ta}->{"lessons"}};
							for my $o_lesson (@o_lessons) {
								next if ($o_lesson eq $lessons[$i]);
								$total_num_associations{$o_lesson} += (0.5 * scalar(@lessons));
							}
						}

						if (not exists $consecutive_lessons{lc($lessons[$i])}) {
							$consecutive_lessons{lc($lessons[$i])} = {};
						}
						for (my $j = 0; $j < @lessons; $j++) {
							next if ($i == $j);
							${$consecutive_lessons{lc($lessons[$i])}}{lc($lessons[$j])}++;
						}
					}
				}
			
				#occasional joint	
				elsif ( $profile_name_6 =~ /^lesson_associations_occasional_joint_lessons_([0-9]+)$/ ) {
					my $id = $1;
					if (exists $profile_vals{"lesson_associations_occasional_joint_format_$id"}) {

						my @lessons = split/,/,lc($profile_vals{$profile_name_6});
						my @periods = split/,/,$profile_vals{"lesson_associations_occasional_joint_format_$id"};

						for ( my $i = 0; $i < @lessons; $i++ ) {
		
							$total_num_associations{$lessons[$i]}+= scalar(@lessons);

							my @tas = ();
							if ( exists $lesson_to_teachers{lc($lessons[$i])} ) {
								@tas = @{$lesson_to_teachers{lc($lessons[$i])}}
							}

							for my $ta ( @tas ) {
								my @o_lessons = @{$teachers{$ta}->{"lessons"}};
								for my $o_lesson (@o_lessons) {
									next if ($o_lesson eq $lessons[$i]);
									$total_num_associations{$o_lesson} += (0.5 * scalar(@lessons)) ;	
								}
							}
	
							if (not exists $occasional_joint_lessons{$lessons[$i]}) {
								$occasional_joint_lessons{$lessons[$i]} = {};
							}

							if ( not exists ${$occasional_joint_lessons{$lessons[$i]}}{$id} ) {
								${$occasional_joint_lessons{$lessons[$i]}}{$id} = {};
							}

							my @lessons_cp = @lessons;
							splice(@lessons_cp, $i, 1);

							my %lessons_hash;
							@lessons_hash{@lessons_cp} = @lessons_cp;

							for my $period (@periods) {
								if ( $period =~ /^(\d+)x(\d+)$/ ) {
									my $num_lessons = $1;
									my $periods_per_lesson = $2;
									for ( my $j = 0; $j < $num_lessons; $j++ ) {
										${$occasional_joint_lessons{$lessons[$i]}}{$id} = {"lessons" => \%lessons_hash, "periods" => $periods_per_lesson };	
									}
								}
							}
						}
					}
				}
			}

			#free up teachers on mornings & afternoons if this
			#mornings;
			if (exists $profile_vals{"teachers_number_free_mornings"} and $profile_vals{"teachers_number_free_mornings"} =~ /^\d+$/) {

				my %mornings = ();
				
				for my $day_org (keys %machine_day_orgs) {
					my $adds = 0;
					JY: for my $event (sort {$a <=> $b} keys %{$machine_day_orgs{$day_org}}) {
						for my $val ( keys %{${$machine_day_orgs{$day_org}}{$event}} ) {
							#seen 
							if ( $val eq "type" and ${${$machine_day_orgs{$day_org}}{$event}}{"type"} == 1 ) {
								if ($adds > 0) {	
									last JY;
								}
							}
							elsif ($val eq "type" and ${${$machine_day_orgs{$day_org}}{$event}}{"type"} == 0 ) {
								$adds++;
								${$mornings{$day_org}}{$event}++;
							}
						}
					}
				}

				
				my $num_free_morns = $profile_vals{"teachers_number_free_mornings"};

				my @teachers = keys %teachers;
				my $num_tas = scalar(keys %teachers);

				#shuffle teachers
				for (my $i = 0; $i < @teachers; $i++) {
					my $cp = $teachers[$i];
					my $selection = int(rand $num_tas);
					$teachers[$i] = $teachers[$selection];
					$teachers[$selection] = $cp;
				}
			
				my $cycles = 0;
				for (my $j = 0; $j < $num_free_morns; $j++) {

					my %processed_tas = ();
	
					for (my $l = 0; $l < @teachers; $l++) {

						#don't double process simult tas
						next if (exists $processed_tas{$teachers[$l]});

						my $day = $selected_days_list[$cycles];

						my $day_org = 0;
						if ( exists $exception_days{$day} ) {
							$day_org = $exception_days{$day};
						}
						my @morn_events = keys %{$mornings{$day_org}};
						
						for (my $k = 0; $k < @morn_events; $k++) {
							${${${$teacher_assignments{$teachers[$l]}}}{$day}}{$morn_events[$k]} = -3;

							#check any simults
							my @lessons = @{$teachers{$teachers[$l]}->{"lessons"}};

							for ( my $m = 0; $m < scalar(@lessons); $m++ ) {
								#has simults
								if ( exists $simult_lessons{ lc($lessons[$m]) } ) {
									for my $simult_lesson ( keys %{$simult_lessons{lc($lessons[$m])}} ) {
										#get teachers
										my @tas = @{$lesson_to_teachers{$simult_lesson}};

										#print "X-Debug-2-0-$j-$teachers[$l]-$m: proc'ng simult dependency $simult_lesson -> " . join(", ", @tas) . "\r\n";

										for ( my $n = 0; $n < scalar(@tas); $n++ ) {
											#free up teacher
											${${${$teacher_assignments{$tas[$n]}}}{$day}}{$morn_events[$k]} = -3;
											#record ta as processed
											$processed_tas{$tas[$n]}++;
										}
									}
								}
							}
						}	

						if (++$cycles >= scalar(@selected_days_list)) {
							$cycles = 0;
						}

					}
				}
			}

			
			#free afternoons.
			my %afternoons = ();
			for my $day_org (keys %machine_day_orgs) {
				my $adds = 0;
				JY: for my $event (sort {$b <=> $a} keys %{$machine_day_orgs{$day_org}}) {
					for my $val ( keys %{${$machine_day_orgs{$day_org}}{$event}} ) {
						#seen 
						if ( $val eq "type" and ${${$machine_day_orgs{$day_org}}{$event}}{"type"} == 1 ) {
							if ($adds > 0) {	
								last JY;
							}
						}
						elsif ($val eq "type" and ${${$machine_day_orgs{$day_org}}{$event}}{"type"} == 0 ) {
							$adds++;
							${$afternoons{$day_org}}{$event}++;
						}
					}
				}
			}

			if (exists $profile_vals{"teachers_number_free_afternoons"} and $profile_vals{"teachers_number_free_afternoons"} =~ /^\d+$/) {
	
				my $num_free_aftes = $profile_vals{"teachers_number_free_afternoons"};

				my @teachers = keys %teachers;
				my $num_tas = scalar(keys %teachers);

				#shuffle teachers
				for (my $i = 0; $i < @teachers; $i++) {
					my $cp = $teachers[$i];
					my $selection = int(rand $num_tas);
					$teachers[$i] = $teachers[$selection];
					$teachers[$selection] = $cp;
				}
			
				my $cycles = 0;
				for (my $j = 0; $j < $num_free_aftes; $j++) {
					my %processed_tas = ();
					#my $cycles = 0;
					for (my $l = 0; $l < @teachers; $l++) {
						#double process simult tas
						next if (exists $processed_tas{$teachers[$l]});

						my $day = $selected_days_list[$cycles];

						my $day_org = 0;
						if ( exists $exception_days{$day} ) {
							$day_org = $exception_days{$day};
						}
						my @afte_events = keys %{$afternoons{$day_org}};
						
						for (my $k = 0; $k < @afte_events; $k++) {
							${${${$teacher_assignments{$teachers[$l]}}}{$day}}{$afte_events[$k]} = -4;

							my @lessons = @{$teachers{$teachers[$l]}->{"lessons"}};

							for ( my $m = 0; $m < scalar(@lessons); $m++ ) {
								#has simults
								if ( exists $simult_lessons{ lc($lessons[$m]) } ) {
									for my $simult_lesson ( keys %{$simult_lessons{lc($lessons[$m])}} ) {
										#get teachers
										my @tas = @{$lesson_to_teachers{$simult_lesson}};

										#print "X-Debug-3-0-$j-$teachers[$l]-$m: proc'ng simult dependency $simult_lesson -> " . join(", ", @tas) . "\r\n";

										for ( my $n = 0; $n < scalar(@tas); $n++ ) {
											#free up teacher
											${${${$teacher_assignments{$tas[$n]}}}{$day}}{$afte_events[$k]} = -4;
											#record ta as processed
											$processed_tas{$tas[$n]}++;
										}
									}
								}
							}
						}

						if (++$cycles >= scalar(@selected_days_list)) {
							$cycles = 0;
						}
					}
				}
			}
			#check if any of the simultaneous lesson
			#associations create a teacher/student conflicts
			if (keys %simult_lessons) {
 
				#1st- teacher conflicts.
				my %teacher_conflicts = ();

				for my $lesson (keys %simult_lessons) {
					
					my @other_lessons = keys %{$simult_lessons{$lesson}};	
					next if (not exists $lesson_to_teachers{$lesson});
					my @lesson_tas = @{$lesson_to_teachers{$lesson}};	

					for my $lesson_ta (@lesson_tas) {

						my @lesson_ta_other_lessons = @{${$teachers{$lesson_ta}}{"lessons"}};	

						for my $lesson_ta_other_lesson (@lesson_ta_other_lessons) {

							for (my $i = 0; $i < @other_lessons; $i++) {
								#this teacher also teaches one of the 
								#other lessons listed in the simultaneous
								#lesson association.
								if ( $other_lessons[$i] eq lc($lesson_ta_other_lesson) ) {
									#may already have a reversed version of this collision--
									#i.e. I'm seeing 'B and A' and I've already seen
									#'A and B'.
									next if (exists ${$teacher_conflicts{$lesson_ta}}{uc($lesson) . " and " . uc($other_lessons[$i]) });	
									if ( not exists $teacher_conflicts{$lesson_ta} ) {
										$teacher_conflicts{$lesson_ta} = {};
									}
									${$teacher_conflicts{$lesson_ta}}{uc($other_lessons[$i]) . " and " . uc($lesson)}++;
								}
							}
						}	
					}
				}

				#2nd- student conflicts
				my %student_conflicts = ();

				my @placeholder_bts = ();
				my @where_clause_args = ();

				for my $selected_class (@selected_classes) {
					#created a copy to avoid
					#dirtying @selected_classes with
					#subsequent edits. (lexical scope biz).
					my $selected_class_cp = $selected_class;
				
					if ($selected_class_cp =~ /(\d+)/) {
						my $yr = $1;
						my $start_yr = ($current_yr - $yr) + 1;
						$selected_class_cp =~ s/\d+//;
						
						push @placeholder_bts, "(start_year=? AND class LIKE ?)";
						push @where_clause_args, $start_yr, "%$selected_class_cp";
					}
				}

				my %classes = ();

				if (@where_clause_args) {					
					my $where_clause_str = join(" OR ", @placeholder_bts);
	
					if ($con) {
						my $prep_stmt7 = $con->prepare("SELECT table_name,class,start_year FROM student_rolls WHERE $where_clause_str");
						if ($prep_stmt7) {
							my $rc = $prep_stmt7->execute(@where_clause_args);
							if ($rc) {
								while (my @rslts = $prep_stmt7->fetchrow_array() ) {
									my $class = $rslts[1];
									my $start_yr = $rslts[2];
									if ($class =~ /\d+/) {
										my $new_yr = ($current_yr - $start_yr) + 1;
										$class =~ s/\d+/$new_yr/;
										$classes{$rslts[0]} = $class;
									}
								}
							}
						}
						else {
							print STDERR "Could not create SELECT FROM profiles statement: ", $con->errstr, $/;
						}
					}

					if (keys %classes) {
						for my $table (keys %classes) {

							my $class_name = $classes{$table};

							my $prep_stmt8 = $con->prepare("SELECT adm,subjects FROM `$table`");
							
							if ($prep_stmt8) {
								my $rc = $prep_stmt8->execute();
								if ($rc) {
								while ( my @rslts = $prep_stmt8->fetchrow_array() ) {

									my %studs_lessons = ();
									my @lesson_parts = split/,/, lc($rslts[1]);
	
	
									@studs_lessons{@lesson_parts} = @lesson_parts;

									for my $lesson (keys %simult_lessons) {

										#only consider lessons for this student's
										#class
										my $plain_lesson = $lesson;
										if ( $plain_lesson =~ /\($class_name\)$/i ) {
											$plain_lesson =~ s/\($class_name\)$//i;
										}
										else {
											next;
										}

										my @other_lessons = keys %{$simult_lessons{$lesson}};

										for ( my $i = 0; $i < @other_lessons; $i++ ) {
											#student is taking both lessons, 
											#this' a conflict.
											#thought mathematics == mathematics(1a). was very foolish.
											
											if ( $other_lessons[$i] =~ /\($class_name\)$/i ) {
												$other_lessons[$i] =~ s/\($class_name\)$//i;
											}
											else {
												next;
											}

											if (exists $studs_lessons{$plain_lesson} and exists $studs_lessons{$other_lessons[$i]}) {
												#check if conflict's mirror twin exists
												if (not exists $student_conflicts{uc($other_lessons[$i]) . " and " . uc($plain_lesson)}) {
													my $conflict_lessons = uc($plain_lesson) . " and " . uc($other_lessons[$i]);
												
													${$student_conflicts{$conflict_lessons}}{$class_name}++;	
												}
											}
										}
									}
								}
								}
							}
						}
					}
				}
				if (keys %teacher_conflicts or keys %student_conflicts) {
					$js =
qq*
<SCRIPT type="text/javascript" language="javascript">
var expanded = [{id: "teacher_conflicts", value: false}, {id: "student_conflicts", value: false} ];

function expand(name) {
	var is_expanded = false;
	var box_id = 0;

	for (var iter in expanded) {
		if (expanded[iter].id == name) {
			if (expanded[iter].value) {
				is_expanded = true;
			}
			box_id = iter;
			break;
		}
	}
	if (is_expanded) {
		document.getElementById(name + "_box").style.display = "none";
		document.getElementById(name + "_label").innerHTML = "Show";
		expanded[box_id].value = false;
	}
	else {
		document.getElementById(name + "_box").style.display = "block";
		document.getElementById(name + "_label").innerHTML = "Hide";
		expanded[box_id].value = true;
	}	
}
</SCRIPT>
*;
					#add teacher conflict warning.
					if (keys %teacher_conflicts) {
						$feedback = '';
						$feedback .=
qq*
<p><span style="color: red">Warning:</span>. One or more of the simultaneous lessons defined will cause some teachers to be assigned multiple lessons simultaneously.(<a href="javascript:expand('teacher_conflicts')"><span id="teacher_conflicts_label">Show</span></a>)
<DIV id="teacher_conflicts_box" style="display: none">
<TABLE border="1">
<THEAD><TH>Teacher<TH>Lessons Affected</THEAD>
<TBODY>
*;

						for my $teacher_id (keys %teacher_conflicts) {
							$feedback .= qq!<TR><TD>$teacher_id (${$teachers{$teacher_id}}{"name"})<TD>!;

							my $affected_lessons = join("<BR>", keys %{$teacher_conflicts{$teacher_id}});
							$feedback .= $affected_lessons;
							
						}
						$feedback .=
qq*
</TBODY>
</TABLE>
<p>Would you like to <a href="/cgi-bin/editteacherlist.cgi">edit the list of teachers</a> or <a href="/cgi-bin/edittimetableprofiles.cgi?profile=$profile">edit this profile</a> to change this?
<HR>
</DIV>
*;	
					}
					
					if (keys %student_conflicts) {
						my %affected_classes = ();

						$feedback .= 
qq*
<p><span style="color: red">Warning:</span>. One or more of the simultaneous lessons defined will cause some students to have multiple lessons scheduled simultaneously.(<a href="javascript:expand('student_conflicts')"><span id="student_conflicts_label">Show</span></a>)
<DIV id="student_conflicts_box" style="display: none">
<TABLE border="1">
<THEAD><TH>Lessons<TH>Students Affected</THEAD>
<TBODY>
*;
						for my $conflict_lesson (keys %student_conflicts) {
							$feedback .= "<TR><TD>$conflict_lesson<TD>";

							my @per_class_cnts = ();
							
							for my $class ( keys %{$student_conflicts{$conflict_lesson}} ) {
								push @per_class_cnts, "$class(${$student_conflicts{$conflict_lesson}}{$class})";
								$affected_classes{$class}++;
							}

							$feedback .= join("<BR>", @per_class_cnts);
						}
						$feedback .=
qq*
</TBODY>
</TABLE>
<p>Would you like to <a href="/cgi-bin/edittimetableprofiles.cgi?profile=$profile"">edit this profile</a> to change this? Or would you rather edit any of the following affected student rolls:
<UL>
*;
						for my $class (keys %classes) {
							my $class_name_0 = $classes{$class};
							if ( exists $affected_classes{$class_name_0} ) {
								$feedback .= qq!<LI><a href="/cgi-bin/editroll.cgi?roll=$class">$class_name_0</a>!;
							}
						}
						$feedback .= "</UL></DIV>";
					}
				}
			}

			my $maximum_number_doubles = 3;
			if (exists $profile_vals{"maximum_number_doubles"} and $profile_vals{"maximum_number_doubles"} =~ /^\d+$/)  {
				$maximum_number_doubles = $profile_vals{"maximum_number_doubles"};
			}

			print "X-Debug-0: $maximum_number_doubles\r\n";
			#exit 0;

			#assign lessons
			my %list_lessons = ();
			my %multi_assigns = ();
			my %daily_doubles = ();

			my %total_num_lessons = ();

			my $num_days = scalar(@selected_days_list);

			my $lesson_cntr = 0;
			for my $class_0 (@selected_classes) {
				$list_lessons{$class_0} = {};	

				my %lesson_struct = %default_lesson_structs;
				#are there any exceptional lesson structures for this class? 
				if (exists $exceptional_lesson_structs{lc($class_0)}) {
					for my $struct_id (keys %{$exceptional_lesson_structs{lc($class_0)}}) {
						my $subject = $profile_vals{"lesson_structure_subject_$struct_id"};
						my $struct = $profile_vals{"lesson_structure_struct_$struct_id"};
						$lesson_struct{$subject} = $struct;
					}
				}

				for my $subject (keys %lesson_struct) {

					my $total_num_lessons = 0;
					
					my @struct = split/,/,$lesson_struct{$subject};

					foreach (@struct) {
						if ($_ =~ /(\d+)x(\d+)/) {

							my $number_lessons     = $1;
							my $periods_per_lesson = $2;

							$total_num_lessons += $number_lessons;

							next if ($number_lessons == 0 or $periods_per_lesson == 0);
							for (my $i = 0; $i < $number_lessons; $i++) {
								
								${$list_lessons{$class_0}}{$lesson_cntr++} = {"subject" => $subject, "periods" => $periods_per_lesson};
							}

							
						}
					}

					$total_num_lessons{lc("$subject($class_0)")} = $total_num_lessons;
 
					if ($total_num_lessons > $num_days) {
						$multi_assigns{lc("$subject($class_0)")}++;	
					}	
				}
	
				#print "X-Debug-size_beforer-$class_0: " . scalar(keys %{$list_lessons{$class_0}}) . "\r\n";	
			}

			my $total_weekly_periods = 0;

			foreach my $day ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday") {
				next if (not exists $selected_days{$day});

				my $organization = 0;
				if (exists $exception_days{$day}) {
					$organization = $exception_days{$day};	
				}

				$total_weekly_periods += $day_org_num_lessons{$organization};
			}

			#check if the user has requested
			#more lessons than are available

			my %over_subscribed_classes = ();
			#perl copy by ref intro'd a bug I'd never have caught
			my %list_lessons_cp = ();

			for my $class_x (keys %list_lessons) {
				for my $less_cntr (keys %{$list_lessons{$class_x}}) {
					for my $val ( keys %{${$list_lessons{$class_x}}{$less_cntr}} ) {
						$list_lessons_cp{$class_x}->{$less_cntr}->{$val} = $list_lessons{$class_x}->{$less_cntr}->{$val}
					}
				}
			}
	
			my %requested_num_lessons = ();

			for my $class (keys %list_lessons_cp) {
	
				for my $less_cntr ( keys %{$list_lessons_cp{$class}} ) {

					my $subj = $list_lessons_cp{$class}->{$less_cntr}->{"subject"};
					next if (not defined $subj);

					my $num_periods = $list_lessons_cp{$class}->{$less_cntr}->{"periods"};

					#delete simults to avoid double counting.
					if ( exists $simult_lessons{lc("$subj($class)")} ) {
						my %seens = ();

						$seens{$class}++;

						my $num_simults = scalar ( keys %{$simult_lessons{lc("$subj($class)")}} );

						OO: for my $class_1 (keys %list_lessons_cp) {
							for my $less_cntr_1 ( keys %{$list_lessons_cp{$class_1}} ) {

								my $subj_1 = $list_lessons_cp{$class_1}->{$less_cntr_1}->{"subject"};
								next if (not defined $subj_1);
 
								my $num_periods_1 =  $list_lessons_cp{$class_1}->{$less_cntr_1}->{"periods"};

								if (exists $simult_lessons{lc("$subj($class)")}->{lc("$subj_1($class_1)")} ) {
									if ($num_periods_1 == $num_periods) {

										#you only want to count each simult lesson
										#per class once 
										if (not exists $seens{$class_1}) {
											$requested_num_lessons{$class_1} += $num_periods;
											$seens{$class_1}++;
										}

										delete	$list_lessons_cp{$class_1}->{$less_cntr_1};
										#to avoid keeping iterating over list_lessons
										#after all simult ass have been seen.
										last OO if (--$num_simults <= 0);	
									}
								}
							}
						}
					}
					#delete one occasional joint lesson
					if ( exists $occasional_joint_lessons{lc("$subj($class)")} ) {

						my %seens;

						$seens{$class}++;

						LL: for my $class_1 (keys %list_lessons_cp) {
							for my $less_cntr_1 ( keys %{$list_lessons_cp{$class_1}} ) {

								my $subj_1 = $list_lessons_cp{$class_1}->{$less_cntr_1}->{"subject"};
								next if (not defined $subj_1);

								my $num_periods_1 = $list_lessons_cp{$class_1}->{$less_cntr_1}->{"periods"};

								if (exists $occasional_joint_lessons{lc("$subj($class)")}->{lc("$subj_1($class_1)")} ) {
									if ($num_periods == $num_periods_1) {

										#you only want to count each simult lesson
										#per class once 
										if (not exists $seens{$class_1}) {
											$requested_num_lessons{$class_1} += $num_periods;
											$seens{$class_1}++;
										}

										$requested_num_lessons{$class_1} += $num_periods;
										delete	$list_lessons_cp{$class_1}->{$less_cntr_1};
										last LL;
									}
								}
							}
						}
					}
					
					$requested_num_lessons{$class} += $num_periods;
				}	
			}

			for my $class_n (keys %list_lessons) {
				#print "X-Debug-size_after-$class_n: " . scalar(keys %{$list_lessons{$class_n}}) . "\r\n";

				for my $cntr (keys %{$list_lessons{$class_n}}) {
					my $subj = $list_lessons{$class_n}->{$cntr}->{"subject"};
					my $periods = $list_lessons{$class_n}->{$cntr}->{"periods"};
					#print "X-Debug-view_lesson-" . $cntr . ": x$periods  $subj($class_n)\r\n";
				}
			}

			for my $class_4 (keys %requested_num_lessons) {	
				if ($requested_num_lessons{$class_4} > $total_weekly_periods) {
					$over_subscribed_classes{lc($class_4)} = $class_4;
				}
			}

			#yes, there're classes with more
			#lessons requested than are available.
			if (keys %over_subscribed_classes) {
				$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Create Timetable</title>
</head>
<body>
$header
<p><span style="color: red">Could not generate timetable</span>. The profile used allocates more lessons in the <em>lessons per subject</em> than are available in the <em>day organization.</em>
*;
				#all classes
				unless (scalar(keys %over_subscribed_classes) == scalar(@selected_classes)) {
					$content .= " The following classes are impacted:<OL>";
					for my $class (keys %over_subscribed_classes) {
						$content .= "<LI>$over_subscribed_classes{$class}";
					}
					$content .= "</OL>";
				}
				
				$content .= qq!<p>To create your timetable, <a href="/cgi-bin/edittimetableprofiles.cgi?profile=$profile">edit this profile</a> ensuring no more than <em>$total_weekly_periods</em> lessons are assigned during the week.!; 
				last MAKE_TIMETABLE;
			}

			#fixed scheduling
			#what are the fixed schedulings defined?

			my $fixed_scheduling_cntr = 0;

			my %period_to_event_cnt;
			my %highest_period;
			
			for my $profile_name_5 (keys %profile_vals) {
				if ( $profile_name_5 =~ /^fixed_scheduling_lessons_(\d+)$/ ) {
					my $id = $1;
					my @lessons = split/,/,$profile_vals{$profile_name_5};

					if (exists $profile_vals{"fixed_scheduling_periods_$id"}) {

						my @bare_periods = split/;/,$profile_vals{"fixed_scheduling_periods_$id"};
						my @refined_periods = ();

						#just remembered that periods and event_cnts are
						#different. harmonize these @ this stage.
						for my $bare_period (@bare_periods) {	

							if ($bare_period =~ /^([^\(]+)\(([0-9]+(?:,[0-9]+)*)\)$/) {	

								my $day = $1;
								my $clean_periods_str = $2;
								
								if (not exists $period_to_event_cnt{$day}) {
									$period_to_event_cnt{$day} = {};
									$highest_period{$day} = 0;
								}

								my $org = 0;
								my $correction = 0;
					
								if (exists $exception_days{$day}) {
									$org = $exception_days{$day};	
								}

								for my $event (sort {$a <=> $b} keys %{$machine_day_orgs{$org}}) {
									my $type = ${${$machine_day_orgs{$org}}{$event}}{"type"};
									#Static event--increment the correction
									if ($type == 1) {
										$correction++;
									}
									else { 
										${$period_to_event_cnt{$day}}{($event+1) - $correction} = $event;
										if ( ($event - $correction) > $highest_period{$day} ) {
											$highest_period{$day} = $event - $correction;
										}
									}
										
								}
								

								#only use days that the user has selected
								if ( exists $selected_days{$day} ) {
									my @clean_periods = split/,/,$clean_periods_str;
									for my $clean_period (@clean_periods) {
										push @refined_periods, "$day($clean_period)";
									}
								}
							}
						}
						for my $lesson (@lessons) {
							if ($lesson =~ /^([^\(]+)\(([^\)]+)\)$/) {
								my $subject = $1;
								my $class = $2;

								$fixed_scheduling{$fixed_scheduling_cntr++} = {"class" => $class, "subject" => $subject, "periods" => \@refined_periods};
							}
						}
					}
				}
			}	

			#try n different combinations before giving up.
			#observed that a few bad initial decisions can
			#make it impossible to create a timetable even with
			#very easy constraints.
			my $max_tries = 26500;
			my %lesson_assignments = ();
			my $exhausted = 0;
			my $multi_assign_gap = 2;

			#trying to avoid retrying the same spots
			my %fixed_sched_tried;
			my %day_assignments;
			my %deleted_lessons = ();
#=pod
			TRY_MAKE_TIMETABLE: for ( my $try = 0; $try < $max_tries; $try++ ) {

			%fixed_sched_tried = ();
			%deleted_lessons = ();
	
			$exhausted = 0;
	
			#assign lessons
			%lesson_assignments = ();
			%day_assignments = ();
			my %unresolved_consecutive = ();
			%daily_doubles = ();

			#print "X-Debug-$try-0: " . scalar(keys %{$machine_day_orgs{"0"}}) . "\r\n";

 			for my $class_0 (@selected_classes) {
				$lesson_assignments{$class_0} = {};

				foreach my $day ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday") {
					next if (not exists $selected_days{$day});
					${$lesson_assignments{$class_0}}{$day} = {};

					my $organization = 0;	

					if (exists $exception_days{$day}) {
						$organization = $exception_days{$day};	
					}
	

					for my $event (sort {$a <=> $b} keys %{$machine_day_orgs{$organization}}) {
						my $type = ${${$machine_day_orgs{$organization}}{$event}}{"type"};
						#Static event--just add it to the lesson assignments
						if ($type == 1) {
							my $event_name = $machine_day_orgs{$organization}->{$event}->{"name"};
							$lesson_assignments{$class_0}->{$day}->{$event}->{$event_name} = 1;
						}
					}
				}
			}

			my $cntr = 0;
			#print "X-Debug-$try-1: " . scalar(keys %{$machine_day_orgs{"0"}}) . "\r\n";

			#assign all fixed schedulings
			FIXED_SCHED_CHECK: for my $fixed_scheduling_cnt ( sort associations_sorter keys %fixed_scheduling) {

				my $class = ${$fixed_scheduling{$fixed_scheduling_cnt}}{"class"};
				my $subject = ${$fixed_scheduling{$fixed_scheduling_cnt}}{"subject"};
				next if (not exists $lesson_to_teachers{lc("$subject($class)")});

				my @lesson_teachers = @{$lesson_to_teachers{lc("$subject($class)")}};
				my @possib_periods = @{${$fixed_scheduling{$fixed_scheduling_cnt}}{"periods"}};

				my @selected_classes_cp = @selected_classes;

				my $num_classes = scalar(@selected_classes_cp);

				for (my $i = 0; $i < $num_classes; $i++)  {

					my $swap_index = int(rand $num_classes);
					my $swap_elem = $selected_classes_cp[$swap_index];
		
					$selected_classes_cp[$swap_index] = $selected_classes_cp[$i];
					$selected_classes_cp[$i] = $swap_elem;
				}

				for my $class_0 (@selected_classes_cp) {
					#process each class at a time.
					next unless ( lc($class) eq lc($class_0) );
					#added sort to ensure lessons with
					#more periods are assigned first.
					for my $lesson_cnt ( sort { ${${$list_lessons{$class_0}}{$b}}{"periods"} <=>  ${${$list_lessons{$class_0}}{$a}}{"periods"} } keys %{$list_lessons{$class_0}} ) {

						my $num_resolved_simults = 0;

						next if (not defined ${${$list_lessons{$class_0}}{$lesson_cnt}}{"subject"});
						
						next unless (${${$list_lessons{$class_0}}{$lesson_cnt}}{"subject"} eq $subject);

						my $num_periods = ${${$list_lessons{$class_0}}{$lesson_cnt}}{"periods"};

						#next;
						#loop until all assigned--
						#avoid infinite loop by recording all values
						#checked and breaking out if all are exhausted.
						#my %tried = ();		

						while (1) {
							my $possib_loc = $possib_periods[int (rand (scalar(@possib_periods)))];

							#already tried this...check if I've exhausted
							#all possibilities.
							if ( scalar(keys %{${$fixed_sched_tried{$class_0}}{$lesson_cnt}}) == scalar(@possib_periods) ) {	
								#print "X-Debug-fixed_sched-$try-" . $cntr++ . ": could not assign $class_0($subject)\r\n";
								$exhausted++;	
								last FIXED_SCHED_CHECK;
								
							}

							#You'll never believe what I did--
							#I did $tried{$possib_loc}++ then did
							#next if (exists $tried{$possib_loc}); 
							#and I took offence when the code kept 
							#cycling on..
							next if (exists ${${$fixed_sched_tried{$class_0}}{$lesson_cnt}}{$possib_loc});

							${${$fixed_sched_tried{$class_0}}{$lesson_cnt}}{$possib_loc}++;	

							if ($possib_loc =~ /^([^\(]+)\(([0-9]+)\)$/) {

								my $day = $1;
								my $period = $2;
								my $event_cnt = ${$period_to_event_cnt{$day}}{$period};

								#need to make allowances for some lessons that need
								#more assignments than are available

								if ( exists ${${$day_assignments{$day}}{$class_0}}{$subject} ) {
									#to avoid doing a daily multi before all days have been served
									#i 1st check that atleast ($num_days) lessons have been assigned
									#
									my $total_weekly_assigns = 0;
									for my $day (keys %day_assignments) {
										for my $class_3 (keys %{$day_assignments{$day}}) {
											next unless (lc($class_3) eq lc($class_0));
											for my $subj ( keys %{${$day_assignments{$day}}{$class_3}} ) {
												$total_weekly_assigns++ if (lc($subj) eq lc($subject));
											}
										}
									}

									unless ( exists $multi_assigns{lc("$subject($class_0)")} and $total_weekly_assigns >= $num_days and ${${$day_assignments{$day}}{$class_0}}{$subject}->{"num_assigns"} < 2 and abs(${${$day_assignments{$day}}{$class_0}}{$subject}->{"last_assign"} - $event_cnt ) >= $multi_assign_gap ) {
										next;
									}

								}

								

								last if (not defined $event_cnt);

								#has this spot been occupied yet?
								next if (exists ${${$lesson_assignments{$class_0}}{$day}}{$event_cnt});

								#is(are) the teacher(s) assigned to this lesson free?
								#my $all_teachers_free = 1;
								my $any_teacher_free = 0;
	
								for my $lesson_teacher (@lesson_teachers) {
									if (not exists ${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_teacher} ) {
										$any_teacher_free = 1;
										last;
									}
								}

								unless ($any_teacher_free) {
									next;
								}

								my $maximum_consecutive_lessons = $highest_period{$day};
								#check if assigning this teacher here
								#will violate the maximum consecutive lessons setting
								if (exists $profile_vals{"teachers_maximum_consecutive_lessons"} and $profile_vals{"teachers_maximum_consecutive_lessons"} =~ /^\d+$/) {
									$maximum_consecutive_lessons = $profile_vals{"teachers_maximum_consecutive_lessons"};

								}

								my $max_consecutive_violated = 0;
								my $num_consecutive = 1;

								#had forgotten to break out if the
								#string of lessons is cut- would hav meant that
								#max_consecutive_lessons was actually just max_(daily)_lessons
								#FIXED
								#1st check backwards
								

								J: for ( my $i = $event_cnt - 1; $i > 0; $i-- ) {

									my $num_engaged_teachers = 0;	
									for my $lesson_ta (@lesson_teachers) {
										if ( exists ${${$teacher_assignments{$day}}{$i}}{$lesson_ta} ) {
											$num_engaged_teachers++;
										}
										else {
											last J; 
										}
									}

									if ( $num_engaged_teachers == scalar(@lesson_teachers) )  {
										if (++$num_consecutive > $maximum_consecutive_lessons) {
											$max_consecutive_violated++;
											last J;	
										}
									}

								}

								

								#now check forward
								if (not $max_consecutive_violated) {

									K: for (my $i = $event_cnt + 1; $i < $highest_period{$day}; $i++) {

										my $num_engaged_teachers = 0;

										for my $lesson_ta (@lesson_teachers) {
											if ( exists ${${$teacher_assignments{$day}}{$i}}{$lesson_ta} ) {
												$num_engaged_teachers++;
											}
											else {
												last K;
											}
										}

										if ( $num_engaged_teachers == scalar(@lesson_teachers) )  {
											if (++$num_consecutive > $maximum_consecutive_lessons) {
												$max_consecutive_violated++;
												last K;	
											}
										}
									}

								}
								
								if ($max_consecutive_violated) {
									next;
								}

								if ($num_periods > 1) {
									if (exists ${$daily_doubles{$class_0}}{$day} and ${$daily_doubles{$class_0}}{$day} > $maximum_number_doubles) {
										#print "X-Debug-$try:fail on doubles lim\r\n";
										next;
									}

									#special add to keep the forces that
									#be happy
									if (lc($subject) eq "mathematics") {
										my $day_org = 0;
										if ( exists $exception_days{$day} ) {
											$day_org = $exception_days{$day};
										}
										#is this an afternoon lesson
										if ( exists ${$afternoons{$day_org}}{$event_cnt} ) {
											next;
										}
									}

									my $resolved = 0;

									my @possib_locs = ($event_cnt);
									my $walk_backs = 0;
									#my @possib_periods = ();

									#1st: look back, see how far
									#back you can stretch this.
									for (my $i = $period - 1; $i > 0; $i--) {
										#is this period contigous with the previous one?
										my $event_cnt_0 = ${$period_to_event_cnt{$day}}{$i};
										#yes, it is.
										if ( ($event_cnt_0 + $walk_backs + 1) == $event_cnt) {
											#has it been occupied yet?
											if (not exists ${${$lesson_assignments{$class_0}}{$day}}{$event_cnt_0}) {
												#unshift @possib_periods, $i;
												$walk_backs++;
												unshift @possib_locs, ${$period_to_event_cnt{$day}}{$i};

												if ( ($walk_backs + 1) == $num_periods ) {
													$resolved = 1;
													last;
												}
											}
										}
										else {
											last;
										}
									}
									
									#now walk forward, see if you can get enough slots
									my $walk_forwards = 0;
									if (not $resolved) {
										for (my $i = $period + 1; $i <= $highest_period{$day}; $i++) {
											#is this period contigous with the previous one?
											my $event_cnt_0 = ${$period_to_event_cnt{$day}}{$i};
											#yes, it is.
											if ( ($event_cnt_0 - ($walk_forwards + 1)) == $event_cnt) {
												#has it been occupied yet?
												if (not exists ${${$lesson_assignments{$class_0}}{$day}}{$event_cnt_0}) {
													#push @possib_periods, $i;
													$walk_forwards++;
													push @possib_locs, ${$period_to_event_cnt{$day}}{$i};

													if ( ($walk_forwards + $walk_backs + 1) == $num_periods ) {
														$resolved = 1;
														last;
													}
												}
											}
											else {
												last;
											}
										}
									}

									if ($resolved) {

										#check if teacher(s) are free
										#my $all_teachers_free = 1;
										my $any_teacher_free = 0;

										PL: for (my $o = 0; $o < @possib_locs; $o++) {	
											for my $lesson_teacher (@lesson_teachers) {
												if (not exists ${${$teacher_assignments{$day}}{$possib_locs[$o]}}{$lesson_teacher} ) {
													$any_teacher_free++;
													last;
												}
											}
										}

										unless ( $any_teacher_free == scalar(@possib_locs) ) {
											next;
										}

										#check if this assign creates violates
										#maximum consecutive lessons per teacher.
										my $max_consecutive_violated = 0;
										my $num_consecutive = $num_periods;

										my $lowest_event_cnt =  $possib_locs[0];
										#1st check backwards

										L: for ( my $i = $lowest_event_cnt - 1; $i > 0; $i-- ) {
											my $num_engaged_teachers = 0;

											for my $lesson_ta (@lesson_teachers) {
												if ( exists ${${$teacher_assignments{$day}}{$i}}{$lesson_ta} ) {
													$num_engaged_teachers++;
												}
												else {
													last L;
												}
											}

											if ( $num_engaged_teachers == scalar(@lesson_teachers) ) {
												if ( ++$num_consecutive > $maximum_consecutive_lessons ) {
													$max_consecutive_violated++;
													last L;
												}
											}
										}

										my $highest_event_cnt = $possib_locs[$#possib_locs];
										#now check forward
										if (not $max_consecutive_violated) {

											M: for (my $i = $highest_event_cnt + 1; $i < $highest_period{$day}; $i++) {
												my $num_engaged_teachers = 0;

												for my $lesson_ta (@lesson_teachers) {
													if ( exists ${${$teacher_assignments{$day}}{$i}}{$lesson_ta} ) {
														$num_engaged_teachers++;
													}
													else {
														last M;
													}
												}

												if ( $num_engaged_teachers == scalar(@lesson_teachers) ) {
													if ( ++$num_consecutive > $maximum_consecutive_lessons ) {
														$max_consecutive_violated++;
														last M;
													}
												}

											}

										}
								
										if ($max_consecutive_violated) {
											next;
										}
										my $mut_ex_violated = 0;
										#does this lesson have any mut_ex
										#lesson associations set?
										if ( exists $mut_ex_lessons{lc("$subject($class)")} ) {
											#my @parellel_lessons = ();
											CHECK_MUT_EX_0: for (my $l = 0; $l < @possib_locs; $l++) {
												CHECK_MUT_EX_1: for my $class_1 (keys %lesson_assignments) {
													for my $day_1 (keys %{$lesson_assignments{$class_1}}) {
														next if ($day ne $day_1);
														for my $event_cnt_1 (keys %{${$lesson_assignments{$class_1}}{$day_1}}) {
															if ($event_cnt_1 eq $possib_locs[$l]) {

																my @subjs =  ();
																if ( exists ${${$lesson_assignments{$class}}{$day_1}}{$event_cnt_1} ) {
																	@subjs = keys %{${${$lesson_assignments{$class_1}}{$day_1}}{$event_cnt_1}};
																}

																for my $subj (@subjs) {
																	#there's a mut_ex collision
																	if (exists ${$mut_ex_lessons{lc("$subject($class)")}}{lc("$subj($class_1)")}) {
																		$mut_ex_violated++;	
																		last CHECK_MUT_EX_0;
																	}
																}
																next CHECK_MUT_EX_1;
															}
														}
													}
												}
											}
										}
										if ($mut_ex_violated) {
											next;
										}
										my $consecutive_violated = 0;
										#consecutive lessons
										 if ( exists $consecutive_lessons{lc("$subject($class_0)")} )  {
											my ($step_back,$step_forth) = (1,1);

											my $org = 0;
											if ( exists $exception_days{$day} ) {
												$org = $exception_days{$day};
											}

											#preceding event is a non-lesson; step back farther (1 step farther).
											if ( exists ${$machine_day_orgs{$org}}{$possib_locs[0] - 1} and ${$machine_day_orgs{$org}}{$possib_locs[0] - 1}->{"type"} eq "1" ) {
												$step_back++;
											}

											#subsequent event is a non-lesson: step forth faarther (1 step farther- a correct impl
											#would step forth as far as necessary)
											if ( exists ${$machine_day_orgs{$org}}{$possib_locs[$#possib_locs] + 1} and ${$machine_day_orgs{$org}}{$possib_locs[$#possib_locs] + 1}->{"type"} eq "1" ) {
												$step_forth++;
											}

											CHECK_CONSECUTIVE_MULTI: for my $class_1 (keys %lesson_assignments) {
												#non-consecutive is designed for the student's 
												#benefit. don't apply across classes
												next unless (lc($class_1) eq lc($class_0));
												for my $day_1 (keys %{$lesson_assignments{$class_1}}) {
													next if ($day ne $day_1);
													for my $event_cnt_1 (keys %{${$lesson_assignments{$class_1}}{$day_1}}) {
													
														
														#is this a subsequent lesson || previous lesson?
														if ( ($event_cnt_1 + $step_back) == $possib_locs[0] or ($event_cnt_1 - $step_forth) == $possib_locs[$#possib_locs] ) {
															#now check if there's a consecutive lesson association

															#next if (not exists ${${${$lesson_assignments{$class_1}}{$day_1}}}{$event_cnt_1});

															my @subjs =();
															if ( exists ${${$lesson_assignments{$class_1}}{$day_1}}{$event_cnt_1} ) {
																 @subjs = keys %{${${$lesson_assignments{$class_1}}{$day_1}}{$event_cnt_1}};
															}
															for my $subj (@subjs) {
																my $lesson = lc ("$subj($class_1)");
																if (exists ${$consecutive_lessons{lc("$subject($class_0)")}}{$lesson}) {
																	$consecutive_violated++;
																	last CHECK_CONSECUTIVE_MULTI;	
																}
															}
														}
													}
												}
											}
										}
										if ($consecutive_violated) {
											next;
										}

										else {
											
											
											
											#check any simultaneous lesson associations
											#and include them too.	
											if ( exists $simult_lessons{lc("$subject($class_0)")} ) {

												my @selected_classes_cp = @selected_classes;

												my $num_classes = scalar(@selected_classes_cp);

												for (my $i = 0; $i < $num_classes; $i++)  {

													my $swap_index = int(rand $num_classes);
													my $swap_elem = $selected_classes_cp[$swap_index];
		
													$selected_classes_cp[$swap_index] = $selected_classes_cp[$i];
													$selected_classes_cp[$i] = $swap_elem;
												}

												for my $class_2 (@selected_classes_cp) {	
													#added sort to ensure lessons with
													#more periods are assigned first.
													MULTI_SIMULT_0: for my $lesson_cnt_1 ( sort { ${${$list_lessons{$class_2}}{$b}}{"periods"} <=>  ${${$list_lessons{$class_2}}{$a}}{"periods"} } keys %{$list_lessons{$class_2}} ) {
				
														my $subj = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"subject"};
														my $num_periods_1 = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"periods"};

														if ( exists ${$simult_lessons{lc("$subject($class_0)")}}{lc("$subj($class_2)")} ) {
															next unless ( $num_periods_1 == $num_periods );
															my @lesson_teachers_1 = @{$lesson_to_teachers{lc("$subj($class_2)")}};

															for (my $p = 0; $p < @possib_locs; $p++) {
																#check if this spot is available
																if (exists ${${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$p]}}{$subj} ) {
																	next;
																	
																	#$exhausted++;
																	#last MULTI_SIMULT_0;
																	
																}
																#has this lesson been assigned for
																#the day?
																if (exists ${${$day_assignments{$day}}{$class_2}}{$subj}) {

																	my $total_weekly_assigns = 0;
																	for my $day (keys %day_assignments) {
																		for my $class_3 (keys %{$day_assignments{$day}}) {
																			next unless (lc($class_3) eq lc($class_2));
																			for my $subj ( keys %{${$day_assignments{$day}}{$class_3}} ) {
																				$total_weekly_assigns++ if (lc($subj) eq lc($subject));
																			}
																		}
																	}

																	unless ( exists $multi_assigns{lc("$subj($class_2)")} and $total_weekly_assigns >= $num_days and ${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"} < 2 and abs(${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} - $possib_locs[0] ) >= $multi_assign_gap ) {

																		#an unassignable simult lesson
																		#means this timetable wont work.
																		$exhausted++;
																		last FIXED_SCHED_CHECK;
																	}
																}
																#check if teachers are available.
																my $num_engaged_teachers = 0;

																for my $lesson_ta_3_b (@lesson_teachers_1) {
																	if (exists ${${$teacher_assignments{$day}}{$possib_locs[$p]}}{$lesson_ta_3_b}) {
																		unless (${${$teacher_assignments{$day}}{$possib_locs[$p]}}{$lesson_ta_3_b} == $lesson_cnt) {	
																			$num_engaged_teachers++;
																		}
																	}
																}

																if ( $num_engaged_teachers == scalar(@lesson_teachers_1) ) {
																	$exhausted++;
																	last FIXED_SCHED_CHECK;
																}

															}
															#don't try to align lessons with
															#different numbers of periods.
															
																#my $num_allocs = 0;
																for (my $m = 0; $m < @possib_locs; $m++) {	
																	#last if ($num_allocs++ > $num_periods_1);
																	${${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$m]}}{$subj}++;
																	
																	${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"}++;
																	${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} = $possib_locs[0];
																	#print "X-Debug-$try-" . $cntr++ . ": set $day x$num_periods $class_2($subj) last assign to $possib_locs[0]\r\n"; 

																	
																	
																	#assign teacher
																	if (not exists $teacher_assignments{$day}) {
																		$teacher_assignments{$day} = {};
																	}
																	if (not exists ${$teacher_assignments{$day}}{$possib_locs[$m]}) {
																		${$teacher_assignments{$day}}{$possib_locs[$m]} = {};
																	}

																	for my $lesson_ta_3 (@lesson_teachers_1) {
																		${${$teacher_assignments{$day}}{$possib_locs[$m]}}{$lesson_ta_3} = $lesson_cnt;
																	}
																}
																$deleted_lessons{$class_2}->{$lesson_cnt_1}++;
																delete $list_lessons{$class_2}->{$lesson_cnt_1};
																#next MULTI_SIMULT_0;
																#last;
																$num_resolved_simults++;
														
														}
													}
												}
											}
											
											#check any occasional joint lessons scheduled.
											if ( exists $occasional_joint_lessons{lc("$subject($class_0)")} ) {
												
												for my $joint_assoc (keys %{$occasional_joint_lessons{lc("$subject($class_0)")}} ) {
													#does this association hav the right number of lessons?
													next unless ( ${${$occasional_joint_lessons{lc("$subject($class_0)")}}{$joint_assoc}}{"periods"} == $num_periods);
										
													my @selected_classes_cp = @selected_classes;

													my $num_classes = scalar(@selected_classes_cp);

													for (my $i = 0; $i < $num_classes; $i++)  {

														my $swap_index = int(rand $num_classes);
														my $swap_elem = $selected_classes_cp[$swap_index];
		
														$selected_classes_cp[$swap_index] = $selected_classes_cp[$i];
														$selected_classes_cp[$i] = $swap_elem;
													}

													for my $class_2 (@selected_classes_cp) {
														#added sort to ensure lessons with
														#more periods are assigned first.
														MULTI_OCCASIONAL_JOINT_0: for my $lesson_cnt_1 ( sort { ${${$list_lessons{$class_2}}{$b}}{"periods"} <=>  ${${$list_lessons{$class_2}}{$a}}{"periods"} } keys %{$list_lessons{$class_2}} ) {
					
															my $subj = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"subject"};
															my $num_periods_1 = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"periods"};

															next unless ($num_periods_1 == $num_periods);
	
															my @lesson_teachers_1 = @{$lesson_to_teachers{lc("$subj($class_2)")}};
	
												if ( exists ${${${$occasional_joint_lessons{lc("$subject($class_0)")}}{$joint_assoc}}{"lessons"}}{lc("$subj($class_2)")} ) {	
													for (my $q = 0; $q < @possib_locs; $q++) {

														#is this spot free?
														if (exists ${${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$q]}}{$subj} ) {
															next MULTI_OCCASIONAL_JOINT_0;	
														}
														#has this lesson been assigned for
														#the day?
														if (exists ${${$day_assignments{$day}}{$class_2}}{$subj}) {

															my $total_weekly_assigns = 0;
															for my $day (keys %day_assignments) {
																for my $class_3 (keys %{$day_assignments{$day}}) {
																	next unless (lc($class_3) eq lc($class_2));
																	for my $subj ( keys %{${$day_assignments{$day}}{$class_3}} ) {
																		$total_weekly_assigns++ if (lc($subj) eq lc($subject));
																	}
																}
															}

															unless ( exists $multi_assigns{lc("$subj($class_2)")} and $total_weekly_assigns >= $num_days and ${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"} < 2 and abs(${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} - $possib_locs[0] ) >= $multi_assign_gap ) {
																next MULTI_OCCASIONAL_JOINT_0;
															}
														}

														#check if teachers are available.
													
														my $num_engaged_teachers = 0;

														for my $lesson_ta_3_b (@lesson_teachers_1) {
															if (exists ${${$teacher_assignments{$day}}{$possib_locs[$q]}}{$lesson_ta_3_b}) {
																unless (${${$teacher_assignments{$day}}{$possib_locs[$q]}}{$lesson_ta_3_b} == $lesson_cnt) {
																	#print "X-Debug-1: allow collision $day, $possib_locs[$q]\r\n";
																	$num_engaged_teachers++;
																}
															}
														}

														if ($num_engaged_teachers == scalar(@lesson_teachers_1)) {
															next MULTI_OCCASIONAL_JOINT_0;
														}
													}

													#don't try to align lessons with
													#different numbers of periods.
													
														
													my $num_allocs = 0;
													for (my $m = 0; $m < @possib_locs; $m++) {	
														#spot taken?
														#next MULTI_OCCASIONAL_JOINT_0 if (exists ${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$m]});
														#
														${${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$m]}}{$subj}++;
														
														${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"}++;
														${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} = $possib_locs[0];
														#print "X-Debug-$try-" . $cntr++ . ": set $day x$num_periods $class_2($subj) last assign to $possib_locs[0]\r\n"; 
														$deleted_lessons{$class_2}->{$lesson_cnt_1}++;
														delete $list_lessons{$class_2}->{$lesson_cnt_1};
																
														#assign teacher
														if (not exists $teacher_assignments{$day}) {
															$teacher_assignments{$day} = {};
														}
														if (not exists ${$teacher_assignments{$day}}{$possib_locs[$m]}) {
															${$teacher_assignments{$day}}{$possib_locs[$m]} = {};
														}

														for my $lesson_ta_3 (@lesson_teachers_1) {
															${${$teacher_assignments{$day}}{$possib_locs[$m]}}{$lesson_ta_3} = $lesson_cnt;
														}
														#delete this joint assoc
														delete $occasional_joint_lessons{lc("$subject($class_0)")}->{$joint_assoc}->{"lessons"}->{lc("$subj($class_2)")};
														#have all lessons in this association been chopped? if yes, delete the association.
														#interesting prob--the joint_assoc id is unique for any group of lessons.
														#if u've exhausted one, u can dafely delete the others. 
													}

													if (keys %{${${$occasional_joint_lessons{lc("$subject($class_0)")}}{$joint_assoc}}{"lessons"}} == 0) {	
														for my $lesson_2 (keys %occasional_joint_lessons) {
															JJ: for my $joint_assoc_2 (keys %{$occasional_joint_lessons{$lesson_2}} ) {
																if ($joint_assoc_2 == $joint_assoc) {
															
																	delete $occasional_joint_lessons{$lesson_2};
														
																	last JJ;
																}
															}
														}
	
														if (scalar(keys %occasional_joint_lessons) == 0) {
													
															%occasional_joint_lessons = ();
														}
													}
																#next MULTI_SIMULT_0;
																#last;
															
														}
													}
												}
												}
											}	
										#assign teacher(s) & lessons
										if (not exists $teacher_assignments{$day}) {
											$teacher_assignments{$day} = {};
										}
	
										for (my $k = 0; $k < @possib_locs; $k++) {

											#assign lesson
											if ( not exists ${${$lesson_assignments{$class_0}}{$day}}{$possib_locs[$k]} ) {
												${${$lesson_assignments{$class_0}}{$day}}{$possib_locs[$k]} = {};
											}

											${${${$lesson_assignments{$class_0}}{$day}}{$possib_locs[$k]}}{$subject}++;
											if (not exists ${$teacher_assignments{$day}}{$possib_locs[$k]}) {
												${$teacher_assignments{$day}}{$possib_locs[$k]} = {};
											}

											#assign teacher
											for my $lesson_ta_2 (@lesson_teachers) {
												${${$teacher_assignments{$day}}{$possib_locs[$k]}}{$lesson_ta_2} = $lesson_cnt;
											}

											${${$day_assignments{$day}}{$class_0}}{$subject}->{"num_assigns"}++;
											${${$day_assignments{$day}}{$class_0}}{$subject}->{"last_assign"} = $possib_locs[0];
											#print "X-Debug-$try-" . $cntr++ . ": set $day x$num_periods $class_0($subject) last assign to $possib_locs[0]\r\n"; 
										}
										#forgot to break out--ended up in a ridiculous loop 
										#then just after that, I forgot to delete the lessson I had
										#just processed.
										
										$deleted_lessons{$class_0}->{$lesson_cnt}++;
										delete $list_lessons{$class_0}->{$lesson_cnt};
										${$daily_doubles{$class_0}}{$day}++;
										#print "X-Debug-$try-" . $cntr++ . ": assigned x2 $class_0($subject) to $day(" . join(", ", @possib_locs) . ")\r\n";
										last;
										}
										
									}
									#keep walking.
									else {
										next;
									}
								}
								#assign teacher & lesson	
								else {
									my $mut_ex_violated = 0;
									#does this lesson have any mut_ex
									#lesson associations set?
									if ( exists $mut_ex_lessons{lc("$subject($class)")} ) {
										
										CHECK_MUT_EX_2: for my $class_1 (keys %lesson_assignments) {
											for my $day_1 (keys %{$lesson_assignments{$class_1}}) {
												next if ($day ne $day_1);
												for my $event_cnt_1 (keys %{${$lesson_assignments{$class_1}}{$day_1}}) {
													if ($event_cnt_1 eq $event_cnt) {
														my @subjs = keys ${${$lesson_assignments{$class_1}}{$day_1}}{$event_cnt_1};
														for my $subj (@subjs) {
															#there's a mut_ex collision
															if (exists ${$mut_ex_lessons{lc("$subject($class)")}}{lc("$subj($class_1)")}) {
																$mut_ex_violated++;	
																last CHECK_MUT_EX_2;
															}
														}
														#next CHECK_MUT_EX_2;
													}
												}
											}
										}
									}
									if ($mut_ex_violated) {
										next;
									}
									my $consecutive_violated = 0;

									if ( exists $consecutive_lessons{lc("$subject($class_0)")} )  {

										my ($step_back,$step_forth) = (1,1);

										my $org = 0;
										if ( exists $exception_days{$day} ) {
											$org = $exception_days{$day};
										}

										#preceding event is a non-lesson; step back farther (1 step farther).
										if ( exists ${$machine_day_orgs{$org}}{$event_cnt - 1} and ${$machine_day_orgs{$org}}{$event_cnt - 1}->{"type"} eq "1" ) {
											$step_back++;
										}

										#subsequent event is a non-lesson: step forth faarther (1 step farther- a correct impl
										#would step forth as far as necessary)
										if ( exists ${$machine_day_orgs{$org}}{$event_cnt + 1} and ${$machine_day_orgs{$org}}{$event_cnt + 1}->{"type"} eq "1" ) {
											$step_forth++;
										}

										CHECK_CONSECUTIVE_SINGLE: for my $class_1 (keys %lesson_assignments) {
											next unless (lc($class_1) eq lc($class_0));
											for my $day_1 (keys %{$lesson_assignments{$class_1}}) {
												next if ($day ne $day_1);
												for my $event_cnt_1 (keys %{${$lesson_assignments{$class_1}}{$day_1}}) {
												
													
													#is this a subsequent lesson || previous lesson?
													if ( ($event_cnt_1 + $step_back) == $event_cnt or ($event_cnt_1 - $step_forth) == $event_cnt ) {
														#now check if there's a consecutive lesson association

														#next if (not exists ${${${$lesson_assignments{$class_1}}{$day_1}}}{$event_cnt_1});

														my @subjs = ();
														if ( exists ${${$lesson_assignments{$class_1}}{$day_1}}{$event_cnt_1} ) {
															@subjs = keys %{${${$lesson_assignments{$class_1}}{$day_1}}{$event_cnt_1}};
														}
														for my $subj (@subjs) {
															my $lesson = lc ("$subj($class_1)");
															if (exists ${$consecutive_lessons{lc("$subject($class_0)")}}{$lesson}) {
																$consecutive_violated++;
																last CHECK_CONSECUTIVE_SINGLE;	
															}
														}
													}
												}
											}
										}	
									}
									if ($consecutive_violated) {
										next;
									}

									if ( exists $simult_lessons{lc("$subject($class_0)")} ) {
										my @selected_classes_cp = @selected_classes;

										my $num_classes = scalar(@selected_classes_cp);

										for (my $i = 0; $i < $num_classes; $i++)  {

											my $swap_index = int(rand $num_classes);
											my $swap_elem = $selected_classes_cp[$swap_index];
		
											$selected_classes_cp[$swap_index] = $selected_classes_cp[$i];
											$selected_classes_cp[$i] = $swap_elem;
										}

										for my $class_2 (@selected_classes_cp) {
											#added sort to ensure lessons with
											#more periods are assigned first.
											SINGLE_SIMULT_0: for my $lesson_cnt_1 ( sort { ${${$list_lessons{$class_2}}{$b}}{"periods"} <=>  ${${$list_lessons{$class_2}}{$a}}{"periods"} } keys %{$list_lessons{$class_2}} ) {	
		
												my $subj = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"subject"};

												my $num_periods_1 = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"periods"};
												
												next unless ($num_periods_1 == 1);

												my @lesson_teachers_1 = @{$lesson_to_teachers{lc("$subj($class_2)")}};

												if ( exists ${$simult_lessons{lc("$subject($class_0)")}}{lc("$subj($class_2)")} ) {
													#don't try to align lessons with
													#different numbers of periods.
													
														
														#check if this spot is available
														if ( exists ${${${$lesson_assignments{$class_2}}{$day}}{$event_cnt}}{$subj} ) {
															next;
															#$exhausted++;	
															#last SINGLE_SIMULT_0;			
														}
														#has this lesson been assigned for
														#the day?
														if (exists ${${$day_assignments{$day}}{$class_2}}{$subj}) {

															my $total_weekly_assigns = 0;
															for my $day (keys %day_assignments) {
																for my $class_3 (keys %{$day_assignments{$day}}) {
																	next unless (lc($class_3) eq lc($class_2));
																	for my $subj ( keys %{${$day_assignments{$day}}{$class_3}} ) {
																		$total_weekly_assigns++ if (lc($subj) eq lc($subject));
																	}
																}
															}

															unless ( exists $multi_assigns{lc("$subj($class_2)")} and $total_weekly_assigns >= $num_days and ${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"} < 2 and abs(${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} - $event_cnt ) >= $multi_assign_gap ) {
																#an unassignable simult lesson
																#means this timetable wont work.
																#print "X-Debug-$try-" . $cntr++ . "-$event_cnt: failed simult\r\n";
																$exhausted++;
																last SINGLE_SIMULT_0;
															}
														}
														#check if teachers are available.
														my $any_teacher_free = 0;

														for my $lesson_ta_3_b (@lesson_teachers_1) {
															if (not exists ${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_ta_3_b}) {
																$any_teacher_free++;	
															}
														}
														unless ($any_teacher_free) {
															#print "X-Debug-$try-" . $cntr++ . "-$event_cnt: failed simult\r\n";
															$exhausted++;
															last SINGLE_SIMULT_0;
														}
														${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"}++;
														${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} = $event_cnt;
														#print "X-Debug-$try-" . $cntr++ . ": set $day x$num_periods $class_2($subj) last assign to $event_cnt\r\n"; 
														$deleted_lessons{$class_2}->{$lesson_cnt_1}++;
														delete $list_lessons{$class_2}->{$lesson_cnt_1};
														
														${${${$lesson_assignments{$class_2}}{$day}}{$event_cnt}}{$subj}++;

														#assign teacher
														if (not exists $teacher_assignments{$day}) {
															$teacher_assignments{$day} = {};
														}
														if (not exists ${$teacher_assignments{$day}}{$event_cnt}) {
															${$teacher_assignments{$day}}{$event_cnt} = {};
														}

														for my $lesson_ta_3 (@lesson_teachers_1) {
															${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_ta_3} = $lesson_cnt;
														}
													
													#next SINGLE_SIMULT_0;
													$num_resolved_simults++;
												}
											}
										}
									}

									#consecutive lesson associations
#check any occasional joint lessons scheduled.
									if ( exists $occasional_joint_lessons{lc("$subject($class_0)")} ) {
											
										for my $joint_assoc (keys %{$occasional_joint_lessons{lc("$subject($class_0)")}} ) {

											
											next if (not defined ${${$occasional_joint_lessons{lc("$subject($class_0)")}}{$joint_assoc}}{"periods"});
											#does this association hav the right number of lessons?
											next unless ( ${${$occasional_joint_lessons{lc("$subject($class_0)")}}{$joint_assoc}}{"periods"} == $num_periods);
										
											my @selected_classes_cp = @selected_classes;

											my $num_classes = scalar(@selected_classes_cp);

											for (my $i = 0; $i < $num_classes; $i++)  {

												my $swap_index = int(rand $num_classes);
												my $swap_elem = $selected_classes_cp[$swap_index];
		
												$selected_classes_cp[$swap_index] = $selected_classes_cp[$i];
												$selected_classes_cp[$i] = $swap_elem;
											}

											for my $class_2 (@selected_classes_cp) {	
												#added sort to ensure lessons with
												#more periods are assigned first.
												SINGLE_OCCASIONAL_JOINT_0: for my $lesson_cnt_1 ( sort { ${${$list_lessons{$class_2}}{$b}}{"periods"} <=>  ${${$list_lessons{$class_2}}{$a}}{"periods"} } keys %{$list_lessons{$class_2}} ) {
				
													my $subj = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"subject"};
													next if (not defined $subj);

													my $num_periods_1 = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"periods"};
													next unless ($num_periods_1 == 1);

													if ( exists ${${${$occasional_joint_lessons{lc("$subject($class_0)")}}{$joint_assoc}}{"lessons"}}{lc("$subj($class_2)")} ) {	
														
													#don't try to align lessons with
													#different numbers of periods.
													
														#is this spot free?
														if (exists ${${${$lesson_assignments{$class_2}}{$day}}{$event_cnt}}{$subj} ) {
															next SINGLE_OCCASIONAL_JOINT_0;	
														}
														#has this lesson been assigned for
														#the day?
														if (exists ${${$day_assignments{$day}}{$class_2}}{$subj}) {

															my $total_weekly_assigns = 0;
															for my $day (keys %day_assignments) {
																for my $class_3 (keys %{$day_assignments{$day}}) {
																	next unless (lc($class_3) eq lc($class_2));
																	for my $subj ( keys %{${$day_assignments{$day}}{$class_3}} ) {
																		$total_weekly_assigns++ if (lc($subj) eq lc($subject));
																	}
																}
															}

															unless ( exists $multi_assigns{lc("$subj($class_2)")} and $total_weekly_assigns >= $num_days and ${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"} < 2 and abs(${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} - $event_cnt ) >= $multi_assign_gap ) {
																next SINGLE_OCCASIONAL_JOINT_0;
															}
														}
														#check if teachers are available.
														my $any_teacher_free = 0;
														my @lesson_teachers_1 = @{$lesson_to_teachers{lc("$subj($class_2)")}};

														for my $lesson_ta_3_b (@lesson_teachers_1) {
															if (not exists ${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_ta_3_b}) {
																$any_teacher_free++;
															}
														}

														unless ( $any_teacher_free ) {
															next SINGLE_OCCASIONAL_JOINT_0;	
														}
															
														${${${$lesson_assignments{$class_2}}{$day}}{$event_cnt}}{$subj}++;
														
														${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"}++;
														${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} = $event_cnt;
														#print "X-Debug-$try-" . $cntr++ . ": set $day x$num_periods $class_2($subj) last assign to $event_cnt\r\n"; 
														$deleted_lessons{$class_2}->{$lesson_cnt_1}++;
														delete $list_lessons{$class_2}->{$lesson_cnt_1};
															
														#assign teacher
														for my $lesson_ta_3 (@lesson_teachers_1) {
															${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_ta_3} = $lesson_cnt_1;
														}
														#delete this joint assoc
														delete $occasional_joint_lessons{lc("$subject($class_0)")}->{$joint_assoc}->{"lessons"}->{lc("$subj($class_2)")};
														#have all lessons in this association been chopped? if yes, delete the association.
														#interesting prob--the joint_assoc id is unique for any group of lessons.
														#if u've exhausted one, u can dafely delete the others. 

										if (keys %{${${$occasional_joint_lessons{lc("$subject($class_0)")}}{$joint_assoc}}{"lessons"}} == 0) {	
											for my $lesson_2 (keys %occasional_joint_lessons) {
												JJ: for my $joint_assoc_2 (keys %{$occasional_joint_lessons{$lesson_2}} ) {
													if ($joint_assoc_2 == $joint_assoc) {
														
														delete $occasional_joint_lessons{$lesson_2};
													
														last JJ;
													}
												}
											}
											if (scalar(keys %occasional_joint_lessons) == 0) {
												
												%occasional_joint_lessons = ();
											}
										}
												
															#next MULTI_SIMULT_0;
															#last;
											
													}
												}
											}
										}
									}
									
									${${${$lesson_assignments{$class_0}}{$day}}{$event_cnt}}{$subject}++;

									#assign teacher
									if (not exists $teacher_assignments{$day}) {
										$teacher_assignments{$day} = {};
									}
									if (not exists ${$teacher_assignments{$day}}{$event_cnt}) {
										${$teacher_assignments{$day}}{$event_cnt} = {};
									}

									for my $lesson_ta_2 (@lesson_teachers) {
										${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_ta_2} = $lesson_cnt;
									}

									${${$day_assignments{$day}}{$class_0}}{$subject}->{"num_assigns"}++;
									${${$day_assignments{$day}}{$class_0}}{$subject}->{"last_assign"} = $event_cnt;
									#print "X-Debug-$try-" . $cntr++ . ": set $day x$num_periods $class_0($subject) last assign to $event_cnt\r\n"; 
									$deleted_lessons{$class_0}->{$lesson_cnt}++;
									delete $list_lessons{$class_0}->{$lesson_cnt};
									#print "X-Debug-$try-" . $cntr++ . ": assigned x1 $class_0($subject) to $day($event_cnt)\r\n";
									last;
								}
							}
						}

						if ( exists $simult_lessons{lc("$subject($class_0)")} ) {
							if (not scalar(keys %{$simult_lessons{lc("$subject($class_0)")}}) == $num_resolved_simults) {
								#print "X-Debug-4-$try-" . $cntr++ .": some simult lessons not assigned\r\n";
								$exhausted++;
								last FIXED_SCHED_CHECK;}
						}
					}
				}
			}

	#print "X-Debug-$try-3: " . scalar(keys %{$machine_day_orgs{"0"}}) . "\r\n";	
	#random assign lessons
	my @classes = @selected_classes;
	my $class_pos = 0;

	my $a_cntr = 0;

RANDOM_ASSIGNS: {

	#print "X-Debug-$try-5: " . scalar(keys %{$machine_day_orgs{"0"}}) . "\r\n";	

	if ($exhausted) {
		#print "X-Debug-$try-" . $cntr++ . ": fall out of RANDOM_ASSIGNS\r\n";
		last RANDOM_ASSIGNS;
	}

	my @selected_classes_cp = @selected_classes;

	my $num_classes = scalar(@selected_classes_cp);

	for (my $i = 0; $i < $num_classes; $i++)  {

		my $swap_index = int(rand $num_classes);
		my $swap_elem = $selected_classes_cp[$swap_index];
		
		$selected_classes_cp[$swap_index] = $selected_classes_cp[$i];
		$selected_classes_cp[$i] = $swap_elem;
	}

	for my $class_0 (@selected_classes_cp) 	{

	#I suspect my inability to assign classes
	#in a tight setup
	#has something to do with the fact that
	#i try the assignment sequantially.
	#trying to randomize class selection
	#without re-writing too much code

		my %possib_locs = ();

		for my $day_2 ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday") {

			next if (not exists $selected_days{$day_2});
	
			my $day_org = 0;

			$day_org = $exception_days{$day_2} if (exists $exception_days{$day_2});
		
				
			for my $event ( keys %{$machine_day_orgs{$day_org}} ) {
				if ( $machine_day_orgs{$day_org}->{$event}->{"type"} == 0 ) {	
					$possib_locs{"$day_2($event)"}++;
				}
			}
			
			for my $class_1 (keys %lesson_assignments) {  
				next unless (lc($class_1) eq lc($class_0));

				for my $day_1 ( keys %{$lesson_assignments{$class_0}} ) {
					next unless (lc($day_2) eq lc($day_1));

					for my $event_1 ( keys %{${$lesson_assignments{$class_1}}{$day_1}} ) {
						delete $possib_locs{"$day_2($event_1)"};
					}
				}
			}
		}

		my @possib_periods = keys %possib_locs;	
			
		if (@possib_periods == 0) {
			#print "X-Debug-$try-" . $cntr++ . "-no_spot_to_try:\r\n";
			$exhausted++;
			last RANDOM_ASSIGNS;
			
		}

		#print "X-Debug-$a_cntr: $class_0\r\n";
		#$a_cntr++;		

		my $run_cnt = 0;	

		PP: for my $lesson_cnt ( sort { my $a_val = 0; my $b_val = 0; $a_val = $total_num_associations{ lc( qq!${${$list_lessons{$class_0}}{$a}}{"subject"}($class_0)!) } if (exists  $total_num_associations{ lc( qq!${${$list_lessons{$class_0}}{$a}}{"subject"}($class_0)!)} ); $b_val = $total_num_associations{ lc( qq!${${$list_lessons{$class_0}}{$b}}{"subject"}($class_0)!) } if (exists  $total_num_associations{ lc( qq!${${$list_lessons{$class_0}}{$b}}{"subject"}($class_0)!)} );   return $b_val <=> $a_val unless ($b_val == $a_val); my $cmp_2 =  ${${$list_lessons{$class_0}}{$b}}{"periods"}  <=> ${${$list_lessons{$class_0}}{$a}}{"periods"};  return $cmp_2 unless ($cmp_2 == 0); return  $total_num_lessons{ lc( qq!${${$list_lessons{$class_0}}{$b}}{"subject"}($class_0)!) } <=> $total_num_lessons{ lc( qq!${${$list_lessons{$class_0}}{$a}}{"subject"}($class_0)!) } } keys %{$list_lessons{$class_0}} ) {
		#
		#PP: for my $lesson_cnt ( sort { my $a_val = 0; my $b_val = 0; $a_val = $total_num_associations{ lc( qq!${${$list_lessons{$class_0}}{$a}}{"subject"}($class_0)!) } if (exists  $total_num_associations{ lc( qq!${${$list_lessons{$class_0}}{$a}}{"subject"}($class_0)!)} ); $b_val = $total_num_associations{ lc( qq!${${$list_lessons{$class_0}}{$b}}{"subject"}($class_0)!) } if (exists  $total_num_associations{ lc( qq!${${$list_lessons{$class_0}}{$b}}{"subject"}($class_0)!)} );   return $b_val <=> $a_val unless ($b_val == $a_val); my $cmp_2 =  ${${$list_lessons{$class_0}}{$b}}{"periods"}  <=> ${${$list_lessons{$class_0}}{$a}}{"periods"};  return $cmp_2 } keys %{$list_lessons{$class_0}} )
			my $cntr = 0;
			my $num_resolved_simults = 0;

			#can't really do a delete on the road
			next if (exists $deleted_lessons{$class_0}{$lesson_cnt});
			#avoid assigning to non-lesson spots
			if (not defined ${${$list_lessons{$class_0}}{$lesson_cnt}}{"subject"}) {
				next;
			}
		
			my $num_periods = ${${$list_lessons{$class_0}}{$lesson_cnt}}{"periods"};

			#next if ($num_periods == 1);

			my $subject = ${${$list_lessons{$class_0}}{$lesson_cnt}}{"subject"};

			#print "X-Debug-$try-$class_0-$lesson_cnt: x$num_periods $subject($class_0)\r\n";
			#next;
			my @lesson_teachers = @{$lesson_to_teachers{lc("$subject($class_0)")}};

			#next;
			#loop until all assigned--
			#avoid infinite loop by recording all values
			#checked and breaking out if all are exhausted.
			my %tried = ();

			RAND_ASSIGN_LOOP: while (1) {	


				$cntr++;

				my $possib_loc = $possib_periods[int (rand (scalar(@possib_periods)))];

				
				#already tried this...check if I've exhausted
				#all possibilities.	
				
				if ( scalar(keys %tried) == scalar(@possib_periods) ) {
					#print "X-Debug-$try-$lesson_cnt-" . $cntr++ . ": couldn't assign x$num_periods $class_0($subject)\r\n";
					#print "X-Debug-$try: exhausted for $subject($class_0)\r\n";
					$exhausted = 1;
					last RANDOM_ASSIGNS;
					#next PP;
				}

				#You'll never believe what I did--
				#I did $tried{$possib_loc}++ then did
				#next if (exists $tried{$possib_loc}); 
				#and I took offence when the code kept 
				#cycling on..
				next if (exists $tried{$possib_loc});

				$tried{$possib_loc}++;

				my ($day,$event_cnt);

				if ($possib_loc =~ /^([^\(]+)\(([0-9]+)\)$/) {

					$day = $1;
					$event_cnt = $2;
					if ( exists ${${$day_assignments{$day}}{$class_0}}{$subject} ) {

						my $total_weekly_assigns = 0;
						for my $day (keys %day_assignments) {
							for my $class_3 ( keys %{$day_assignments{$day}} ) {
								next unless (lc($class_3) eq lc($class_0));
								for my $subj ( keys %{${$day_assignments{$day}}{$class_3}} ) {
									$total_weekly_assigns++ if (lc($subj) eq lc($subject));
								}
							}
						}

						#my $diff = abs(${${$day_assignments{$day}}{$class_0}}{$subject}->{"last_assign"} - $event_cnt );
						unless ( exists $multi_assigns{lc("$subject($class_0)")} and $total_weekly_assigns >= $num_days and ${${$day_assignments{$day}}{$class_0}}{$subject}->{"num_assigns"} < 2 and abs(${${$day_assignments{$day}}{$class_0}}{$subject}->{"last_assign"} - $event_cnt ) >= $multi_assign_gap ) {
							next RAND_ASSIGN_LOOP;
						}

					}
				}

				else {	
					last RAND_ASSIGN_LOOP;
				}

				#has this spot been occupied yet?
				next RAND_ASSIGN_LOOP if ( exists ${${$lesson_assignments{$class_0}}{$day}}{$event_cnt} and scalar(keys %{${${$lesson_assignments{$class_0}}{$day}}{$event_cnt}}) > 0 );

				#is(are) the teacher(s) assigned to this lesson free?
				#my $all_teachers_free = 1;
				my $any_teacher_free = 0;

				for my $lesson_teacher (@lesson_teachers) {
					if ( not exists ${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_teacher} ) {	
						$any_teacher_free = 1;	
						last;
					}
				}

				unless ($any_teacher_free) {
					next RAND_ASSIGN_LOOP;
				}
 
				my $maximum_consecutive_lessons = $highest_period{$day};
				#check if assigning this teacher here
				#will violate the maximum consecutive lessons setting
				if (exists $profile_vals{"teachers_maximum_consecutive_lessons"} and $profile_vals{"teachers_maximum_consecutive_lessons"} =~ /^\d+$/) {
					$maximum_consecutive_lessons = $profile_vals{"teachers_maximum_consecutive_lessons"};
				}

				my $max_consecutive_violated = 0;
				my $num_consecutive = 1;

				#had forgotten to break out if the
				#string of lessons is cut- would hav meant that
				#max_consecutive_lessons was actually just max_(daily)_lessons
				#FIXED
				#1st check backwards
				J: for ( my $i = $event_cnt - 1; $i > 0; $i-- ) {

					my $num_engaged_teachers = 0;
					for my $lesson_ta (@lesson_teachers) {
						if ( exists ${${$teacher_assignments{$day}}{$i}}{$lesson_ta} ) {
							$num_engaged_teachers++;
						}
						else {
							last J; 
						}
					}

					if ($num_engaged_teachers == scalar(@lesson_teachers)) {
						if (++$num_consecutive > $maximum_consecutive_lessons) {
							$max_consecutive_violated++;
							last J;
						}
					}

				}

				#now check forward
				if (not $max_consecutive_violated) {
					K: for (my $i = $event_cnt + 1; $i < $highest_period{$day}; $i++) {
					
						my $num_engaged_teachers = 0;

						for my $lesson_ta (@lesson_teachers) {

							if ( exists ${${$teacher_assignments{$day}}{$i}}{$lesson_ta} ) {
								$num_engaged_teachers++;
							}
							else {
								last K;
							}
						}

						if ( $num_engaged_teachers == scalar(@lesson_teachers) ) {
							if (++$num_consecutive > $maximum_consecutive_lessons) {
								$max_consecutive_violated++;
								last K;
							}						
						}
					}
				}
						
				if ($max_consecutive_violated) {
					next RAND_ASSIGN_LOOP;
				}


				if ($num_periods > 1) {

					if ( exists ${$daily_doubles{$class_0}}{$day} and ${$daily_doubles{$class_0}}{$day} > $maximum_number_doubles ) {
						#print "X-Debug-$try:fail on doubles lim\r\n";
						next;
					}

					if (lc($subject) eq "mathematics") {
						my $day_org = 0;
						if ( exists $exception_days{$day} ) {
							$day_org = $exception_days{$day};
						}
						#is this an afternoon lesson
						if ( exists ${$afternoons{$day_org}}{$event_cnt} ) {
							next;
						}
					}

					my $resolved = 0;

					my @possib_locs = ($event_cnt);
					my $walk_backs = 0;
					#my @possib_periods = ();

					#TODO: replace this with smthng
					#that uses machine day orgs;
					#
					#1st: look back, see how far
					#back you can stretch this.

					my $day_org = exists $exception_days{$day} ? $exception_days{$day} : 0;

					
					for (my $i = $event_cnt - 1; $i >= 0; $i--) {
						#we want to break out when we see a non-lesson 
						#event
						if ( $machine_day_orgs{$day_org}->{$i}->{"type"} == 0 ) {	
							#has it been occupied yet?
							if (not exists ${${$lesson_assignments{$class_0}}{$day}}{$i} or scalar(keys %{${${$lesson_assignments{$class_0}}{$day}}{$i}}) == 0 ) {
								#unshift @possib_locs, $i;
								$walk_backs++;
								unshift @possib_locs, $i;
								

								if ( ($walk_backs + 1) >= $num_periods ) {
									$resolved = 1;
									last;
								}
							}
							else {
								last;
							}
						}
						#reached edge
						else {
							last;
						}
					}
								
					#now walk forward, see if you can get enough slots
					my $walk_forwards = 0;
					if (not $resolved) {

						for ( my $i = $event_cnt + 1; ; $i++ ) {
							
							#break out at seeing a non-lesson event or when u seen NO EVENT
							#I didn't know that checking for a key in a hash actually creates
							#the key--many nights of good sleep were lost as a result
							#
							if ( exists $machine_day_orgs{$day_org}->{$i} and $machine_day_orgs{$day_org}->{$i}->{"type"} == 0 ) {	
								#has it been occupied yet?
								if ( not exists ${${$lesson_assignments{$class_0}}{$day}}{$i} or scalar(keys %{${${$lesson_assignments{$class_0}}{$day}}{$i}}) == 0) {
									#push @possib_periods, $i;
									$walk_forwards++;
									push @possib_locs, $i;

									if ( ($walk_forwards + $walk_backs + 1) >= $num_periods ) {
										$resolved = 1;
										last;
									}
								}
								else {
									last;
								}
							}
							else {
								last;
							}
						}
					}
	
					if ($resolved) {
						
						#check if teacher(s) are free
						#my $all_teachers_free = 1;
						my $any_teacher_free = 0;

							PL: for (my $o = 0; $o < @possib_locs; $o++) {	
								for my $lesson_teacher (@lesson_teachers) {
									if ( not exists ${${$teacher_assignments{$day}}{$possib_locs[$o]}}{$lesson_teacher} ) {
										$any_teacher_free++;
										last;
									}
								}
							}

							unless ( $any_teacher_free == scalar(@possib_locs)) {
								next RAND_ASSIGN_LOOP;
							}

							#check if this assign creates violates
							#maximum consecutive lessons per teacher.
							my $max_consecutive_violated = 0;
							my $num_consecutive = $num_periods;

							my $lowest_event_cnt =  $possib_locs[0];
							#1st check backwards

							L: for ( my $i = $lowest_event_cnt - 1; $i > 0; $i-- ) {

								my $num_engaged_teachers = 0;

								for my $lesson_ta (@lesson_teachers) {

									if ( exists ${${$teacher_assignments{$day}}{$i}}{$lesson_ta} ) {
										$num_engaged_teachers++;
									}
									else {
										last L;
									}
								}

								if ( $num_engaged_teachers == scalar(@lesson_teachers) ) {
									if ( ++$num_consecutive > $maximum_consecutive_lessons ) {
										$max_consecutive_violated++;
										last L;
									}
								}
							}

							my $highest_event_cnt = $possib_locs[$#possib_locs];
							#now check forward
							if (not $max_consecutive_violated) {
								M: for (my $i = $highest_event_cnt + 1; $i < $highest_period{$day}; $i++) {

									my $num_engaged_teachers = 0;

									for my $lesson_ta (@lesson_teachers) {
										if ( exists ${${$teacher_assignments{$day}}{$i}}{$lesson_ta} ) {
											$num_engaged_teachers++;
										}
										else {
											last M;
										}
									}

									if ( $num_engaged_teachers == scalar(@lesson_teachers) ) {

										if (++$num_consecutive > $maximum_consecutive_lessons) {
											$max_consecutive_violated++;
											last M;
										}

									}
								}
							}
								
							if ($max_consecutive_violated) {
								next RAND_ASSIGN_LOOP;
							}

							my $mut_ex_violated = 0;
							#does this lesson have any mut_ex
							#lesson associations set?
							if ( exists $mut_ex_lessons{lc("$subject($class_0)")} ) {
								#my @parellel_lessons = ();
								CHECK_MUT_EX_0: for (my $l = 0; $l < @possib_locs; $l++) {
									CHECK_MUT_EX_1: for my $class_1 (keys %lesson_assignments) {
										for my $day_1 (keys %{$lesson_assignments{$class_1}}) {
											next if ($day ne $day_1);
											for my $event_cnt_1 (keys %{${$lesson_assignments{$class_1}}{$day_1}}) {
												if ($event_cnt_1 eq $possib_locs[$l]) {
													my @subjs =  ();
													if (exists ${${$lesson_assignments{$class_1}}{$day_1}}{$event_cnt_1}) {
														@subjs = keys %{${${$lesson_assignments{$class_1}}{$day_1}}{$event_cnt_1}};
													}
													for my $subj (@subjs) {
														#there's a mut_ex collision
														if (exists ${$mut_ex_lessons{lc("$subject($class_0)")}}{lc("$subj($class_1)")}) {
															$mut_ex_violated++;	
															last CHECK_MUT_EX_0;
														}
													}
													next CHECK_MUT_EX_1;
												}
											}
										}
									}
								}
							}
							if ($mut_ex_violated) {
								next RAND_ASSIGN_LOOP;
							}

							my $consecutive_violated = 0;
							#consecutive lessons
							if ( exists $consecutive_lessons{lc("$subject($class_0)")} )  {
								my ($step_back,$step_forth) = (1,1);

								my $org = 0;
								if ( exists $exception_days{$day} ) {
									$org = $exception_days{$day};
								}

								#preceding event is a non-lesson; step back farther (1 step farther).
								if ( exists ${$machine_day_orgs{$org}}{$possib_locs[0] - 1} and ${$machine_day_orgs{$org}}{$possib_locs[0] - 1}->{"type"} eq "1" ) {
									$step_back++;
								}

								#subsequent event is a non-lesson: step forth faarther (1 step farther- a correct impl
								#would step forth as far as necessary)
								if ( exists ${$machine_day_orgs{$org}}{$possib_locs[$#possib_locs] + 1} and ${$machine_day_orgs{$org}}{$possib_locs[$#possib_locs] + 1}->{"type"} eq "1" ) {
									$step_forth++;
								}

								CHECK_CONSECUTIVE_MULTI: for my $class_1 (keys %lesson_assignments) {
									next unless (lc($class_1) eq lc($class_0));
									for my $day_1 (keys %{$lesson_assignments{$class_1}}) {
										next if ($day ne $day_1);
										for my $event_cnt_1 (keys %{${$lesson_assignments{$class_1}}{$day_1}}) {
										
														
											#is this a subsequent lesson || previous lesson?
											if ( ($event_cnt_1 + $step_back) == $possib_locs[0] or ($event_cnt_1 - $step_forth) == $possib_locs[$#possib_locs] ) {
												#now check if there's a consecutive lesson association

												#next if (not exists ${${${$lesson_assignments{$class_1}}{$day_1}}}{$event_cnt_1});

												my @subjs = ();
												if (exists ${${$lesson_assignments{$class_1}}{$day_1}}{$event_cnt_1}) {
													@subjs = keys %{${${$lesson_assignments{$class_1}}{$day_1}}{$event_cnt_1}};
												}

												for my $subj (@subjs) {
													my $lesson = lc ("$subj($class_1)");
													if (exists ${$consecutive_lessons{lc("$subject($class_0)")}}{$lesson}) {
														$consecutive_violated++;
														last CHECK_CONSECUTIVE_MULTI;	
													}
												}
											}
										}
									}
								}
							}
							if ($consecutive_violated) {
								next RAND_ASSIGN_LOOP;
							}

							else {
							
								#check any simultaneous lesson associations
								#and include them too.	
								#
								if ( exists $simult_lessons{lc("$subject($class_0)")} ) {

									my @selected_classes_cp = @selected_classes;

									my $num_classes = scalar(@selected_classes_cp);

									for (my $i = 0; $i < $num_classes; $i++)  {

										my $swap_index = int(rand $num_classes);
										my $swap_elem = $selected_classes_cp[$swap_index];
		
										$selected_classes_cp[$swap_index] = $selected_classes_cp[$i];
										$selected_classes_cp[$i] = $swap_elem;
									}

									for my $class_2 (@selected_classes_cp) {
										#added sort to ensure lessons with
										#more periods are assigned first.
										MULTI_SIMULT_0: for my $lesson_cnt_1 ( sort { ${${$list_lessons{$class_2}}{$b}}{"periods"} <=>  ${${$list_lessons{$class_2}}{$a}}{"periods"} } keys %{$list_lessons{$class_2}} ) {

										next if (not defined ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"subject"});
				
										my $subj = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"subject"};
										my $num_periods_1 = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"periods"};

										if ( exists ${$simult_lessons{lc("$subject($class_0)")}}{lc("$subj($class_2)")} ) {

											
											next unless ( $num_periods_1 == $num_periods );

											my @lesson_teachers_1 = @{$lesson_to_teachers{lc("$subj($class_2)")}};	

											for (my $p = 0; $p < @possib_locs; $p++) {
												my $any_teacher_free = 0;
												#check if this spot is available
												
												#avoid double alloc spots
												if (exists ${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$p]} and scalar(keys  %{${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$p]}}) > 0) {
	
													my @curr_lessons = keys %{${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$p]}};

													for (my $i = 0; $i < @curr_lessons; $i++) {
														#next if (lc($curr_lessons[$i]) eq lc($subject) and lc($class_0) eq lc($class_2));
														#check 
														unless ( exists ${$simult_lessons{lc("$subject($class_0)")}}{lc("$curr_lessons[$i]($class_2)")} ) {	
															#print "X-Debug-$try-" . $cntr++ . ": could not assign simult $subject($class_0) occupied by $curr_lessons[$i]($class_2)\r\n";
															$exhausted++;
															last RANDOM_ASSIGNS;
														}
													}
												}

												if (exists ${${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$p]}}{$subj} ) {	
													
													next;
													
													#$exhausted++;
													#last RANDOM_ASSIGNS;
													#last MULTI_SIMULT_0;
																	
												}
												#has this lesson been assigned for
												#the day?
												if (exists ${${$day_assignments{$day}}{$class_2}}{$subj}) {

													my $total_weekly_assigns = 0;
													for my $day ( keys %day_assignments ) {
														for my $class_3 ( keys %{$day_assignments{$day}} ) {
															next unless (lc($class_3) eq lc($class_2));
															for my $subj ( keys %{${$day_assignments{$day}}{$class_3}} ) {
																$total_weekly_assigns++ if (lc($subj) eq lc($subject));
															}
														}
													}

													unless ( exists $multi_assigns{lc("$subj($class_2)")} and $total_weekly_assigns >= $num_days and ${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"} < 2 and abs(${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} - $possib_locs[$p] ) >= $multi_assign_gap ) {
														#an unassignable simult lesson
														#means this timetable wont work.
														next;
														#$exhausted++;
														#last RANDOM_ASSIGNS;
													}																
												}
												#check if teachers are available.
												
												
												
												for my $lesson_ta_3_b (@lesson_teachers_1) {
													#found probs when checking for TA availability
													#when a teacher is sched'd to teach simult lessons
													#the system will refuse to assign more lessons because
													#the teacher is booked. Changed the code so that it checks 
													#if the lesson that is creating the conflict has a simult assoc
													#with the lessons I'm trying to assign.	
													#$all_teachers_free = 0;
													if (not exists ${${$teacher_assignments{$day}}{$possib_locs[$p]}}{$lesson_ta_3_b} ) {
														$any_teacher_free = 1;		
														last;
													}
													if ( ${${$teacher_assignments{$day}}{$possib_locs[$p]}}{$lesson_ta_3_b} == $lesson_cnt ) {
														#print "X-Debug-2-$try-$lesson_cnt: allow collision $lesson_ta_3_b; $day, $possib_locs[$p]\r\n";
														$any_teacher_free = 1;	
														last;
													}
												}

												unless ($any_teacher_free) {

													#print "X-Debug-$try-" . $cntr++ . ": could not assign simult $subj($class_2) teacher taken\r\n";

													$exhausted++;
													last RANDOM_ASSIGNS;
												}
												
											}

											
	
											#don't try to align lessons with
											#different numbers of periods.
										
											#my $num_allocs = 0;
											for (my $m = 0; $m < @possib_locs; $m++) {	
												
												${${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$m]}}{$subj}++;
													
												#assign teacher
	
												for my $lesson_ta_3 (@lesson_teachers_1) {
													${${$teacher_assignments{$day}}{$possib_locs[$m]}}{$lesson_ta_3} = $lesson_cnt;
												}
												${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"}++;
												${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} = $possib_locs[0];
												#print "X-Debug-$try-" . $cntr++ . ": set $day x$num_periods $class_2($subj) last assign to $possib_locs[0]\r\n"; 
											}

											$deleted_lessons{$class_2}->{$lesson_cnt_1}++;	
											delete $list_lessons{$class_2}->{$lesson_cnt_1};
											
											#redo MULTI_SIMULT_0;
											#last;
											$num_resolved_simults++;
									}
								}
							}
						}
											
						#check any occasional joint lessons scheduled.
						if ( exists $occasional_joint_lessons{lc("$subject($class_0)")} ) {
	
							for my $joint_assoc (keys %{$occasional_joint_lessons{lc("$subject($class_0)")}} ) {
								#does this association hav the right number of lessons?
								next unless ( ${${$occasional_joint_lessons{lc("$subject($class_0)")}}{$joint_assoc}}{"periods"} == $num_periods);

								my @selected_classes_cp = @selected_classes;

								my $num_classes = scalar(@selected_classes_cp);

								for (my $i = 0; $i < $num_classes; $i++)  {

									my $swap_index = int(rand $num_classes);
									my $swap_elem = $selected_classes_cp[$swap_index];
		
									$selected_classes_cp[$swap_index] = $selected_classes_cp[$i];
									$selected_classes_cp[$i] = $swap_elem;
								}

								for my $class_2 (@selected_classes_cp) {
									#added sort to ensure lessons with
									#more periods are assigned first.
									MULTI_OCCASIONAL_JOINT_0: for my $lesson_cnt_1 ( sort { ${${$list_lessons{$class_2}}{$b}}{"periods"} <=>  ${${$list_lessons{$class_2}}{$a}}{"periods"} } keys %{$list_lessons{$class_2}} ) {
				
									my $subj = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"subject"};
									my $num_periods_1 = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"periods"};

									next unless ($num_periods_1 == $num_periods);

									my @lesson_teachers_1 = @{$lesson_to_teachers{lc("$subj($class_2)")}};

									if ( exists ${${${$occasional_joint_lessons{lc("$subject($class_0)")}}{$joint_assoc}}{"lessons"}}{lc("$subj($class_2)")} ) {	
										for (my $q = 0; $q < @possib_locs; $q++) {

											#is this spot free?
											#avoid double alloc spots
											if ( exists ${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$q]} and scalar(keys %{${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$q]}}) > 0 ) {

												my @curr_lessons = keys %{${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$q]}};

												for (my $i = 0; $i < @curr_lessons; $i++) {
													#next if (lc($curr_lessons[$i]) eq lc($subject) and lc($class_0) eq lc($class_2));
													#check 
													unless ( exists ${$occasional_joint_lessons{lc("$subject($class_0)")}}{lc("$curr_lessons[$i]($class_2)")} ) {	
														$exhausted++;
														last RANDOM_ASSIGNS;
													}
												}
											}


											if (exists ${${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$q]}}{$subj} ) {
												#$exhausted++;
												#last RANDOM_ASSIGNS;
												next MULTI_OCCASIONAL_JOINT_0;	
											}
										#has this lesson been assigned for
											#the day?
											if (exists ${${$day_assignments{$day}}{$class_2}}{$subj}) {

												my $total_weekly_assigns = 0;
												for my $day (keys %day_assignments) {
													for my $class_3 ( keys %{$day_assignments{$day}} ) {
														next unless (lc($class_3) eq lc($class_2));
														for my $subj ( keys %{${$day_assignments{$day}}{$class_3}} ) {
															$total_weekly_assigns++ if (lc($subj) eq lc($subject));
														}
													}
												}

												unless ( exists $multi_assigns{lc("$subj($class_2)")} and $total_weekly_assigns >= $num_days and ${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"} < 2 and abs(${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} - $possib_locs[$q] ) >= $multi_assign_gap ) {
													next MULTI_OCCASIONAL_JOINT_0;	
												}
											}
											#check if teachers are available.
											my $num_engaged_teachers = 0;

											for my $lesson_ta_3_b (@lesson_teachers_1) {
												if (exists ${${$teacher_assignments{$day}}{$possib_locs[$q]}}{$lesson_ta_3_b}) {
													unless ( ${${$teacher_assignments{$day}}{$possib_locs[$q]}}{$lesson_ta_3_b} == $lesson_cnt ) {
														#print "X-Debug-4-$try-$lesson_cnt: allow collision $day, $possib_locs[$q]\r\n";
														$num_engaged_teachers++;
													}
												}
											}

											if ( $num_engaged_teachers == scalar(@lesson_teachers_1) ) {
												next MULTI_OCCASIONAL_JOINT_0;
											}

											}
										}
										#don't try to align lessons with
										#different numbers of periods.
										
													
										#my $num_allocs = 0;
										for (my $m = 0; $m < @possib_locs; $m++) {	
											#spot taken?
											#next MULTI_OCCASIONAL_JOINT_0 if (exists ${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$m]});

											#
											${${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$m]}}{$subj}++;
											
											${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"}++;
											${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} = $possib_locs[0];
											#print "X-Debug-$try-" . $cntr++ . ": set $day x$num_periods $class_2($subj) last assign to $possib_locs[0]\r\n";
											$deleted_lessons{$class_2}->{$lesson_cnt_1}++;
											delete $list_lessons{$class_2}->{$lesson_cnt_1};
															
											#assign teacher
											if (not exists $teacher_assignments{$day}) {
												$teacher_assignments{$day} = {};
											}
											if (not exists ${$teacher_assignments{$day}}{$possib_locs[$m]}) {
												${$teacher_assignments{$day}}{$possib_locs[$m]} = {};
											}

											for my $lesson_ta_3 (@lesson_teachers_1) {
												${${$teacher_assignments{$day}}{$possib_locs[$m]}}{$lesson_ta_3} = $lesson_cnt;
											}
											#delete this joint assoc
											delete $occasional_joint_lessons{lc("$subject($class_0)")}->{$joint_assoc}->{"lessons"}->{lc("$subj($class_2)")};
											#have all lessons in this association been chopped? if yes, delete the association.
											#interesting prob--the joint_assoc id is unique for any group of lessons.
											#if u've exhausted one, u can dafely delete the others. 
										}

										if (scalar(keys %{${${$occasional_joint_lessons{lc("$subject($class_0)")}}{$joint_assoc}}{"lessons"}}) == 0) {	
											for my $lesson_2 (keys %occasional_joint_lessons) {
												JJ: for my $joint_assoc_2 (keys %{$occasional_joint_lessons{$lesson_2}} ) {
													if ($joint_assoc_2 == $joint_assoc) {
												
														delete $occasional_joint_lessons{$lesson_2};
												
														last JJ;
													}
												}
											}
											if (scalar(keys %occasional_joint_lessons) == 0) {
											
												%occasional_joint_lessons = ();
											}
										}
										#next MULTI_SIMULT_0;
										#last;
										
									}
								}
							}
						}
				

						#assign teacher(s) & lessons
						if (not exists $teacher_assignments{$day}) {
							$teacher_assignments{$day} = {};
						}
	
						for (my $k = 0; $k < @possib_locs; $k++) {
							#assign lesson
							if ( not exists ${${$lesson_assignments{$class_0}}{$day}}{$possib_locs[$k]} ) {
								${${$lesson_assignments{$class_0}}{$day}}{$possib_locs[$k]} = {};
							}

							${${${$lesson_assignments{$class_0}}{$day}}{$possib_locs[$k]}}{$subject}++;

							if (not exists ${$teacher_assignments{$day}}{$possib_locs[$k]}) {
								${$teacher_assignments{$day}}{$possib_locs[$k]} = {};
							}

							#assign teacher
							for my $lesson_ta_2 (@lesson_teachers) {
								${${$teacher_assignments{$day}}{$possib_locs[$k]}}{$lesson_ta_2} = $lesson_cnt;
							}

							${${$day_assignments{$day}}{$class_0}}{$subject}->{"num_assigns"}++;
							${${$day_assignments{$day}}{$class_0}}{$subject}->{"last_assign"} = $possib_locs[0];
							#print "X-Debug-$try-" . $cntr++ . ": set $day x$num_periods $class_0($subject) last assign to $possib_locs[0]\r\n"; 
						}

						#forgot to break out--ended up in a ridiculous loop 
						#then just after that, I forgot to delete the lessson I had
						#just processed.
						
						#print "X-Debug-$try-$event_cnt-$class_0" . $cntr++ . ": assigned x$num_periods $subject($class_0)\r\n";

						$deleted_lessons{$class_0}->{$lesson_cnt}++;
						delete $list_lessons{$class_0}->{$lesson_cnt};
						${$daily_doubles{$class_0}}{$day}++;
						last RAND_ASSIGN_LOOP;

					}
				}
				#keep walking.
				else {	
					next RAND_ASSIGN_LOOP;
				}
				
			}

			else {
				
				#check if this assign creates violates
				#maximum consecutive lessons per teacher.
				my $max_consecutive_violated = 0;
				my $num_consecutive = $num_periods;
	
				#1st check backwards
				L: for ( my $i = $event_cnt - 1; $i > 0; $i-- ) {
				
					my $num_engaged_teachers = 0;

					for my $lesson_ta (@lesson_teachers) {

						if ( exists ${${$teacher_assignments{$day}}{$i}}{$lesson_ta} ) {
							$num_engaged_teachers++;	
						}
						else {
							last L;
						}

					}

					if ( $num_engaged_teachers == scalar(@lesson_teachers) ) {
						if (++$num_consecutive > $maximum_consecutive_lessons) {
							$max_consecutive_violated++;
							last L;
						}
					}
				}
	
				#now check forward
				if (not $max_consecutive_violated) {
					M: for (my $i = $event_cnt + 1; $i < $highest_period{$day}; $i++) {

						my $num_engaged_teachers = 0;

						for my $lesson_ta (@lesson_teachers) {
							if ( exists ${${$teacher_assignments{$day}}{$i}}{$lesson_ta} ) {
								$num_engaged_teachers++;
							}
							else {
								last M;
							}
						}
						if ($num_engaged_teachers == scalar(@lesson_teachers)) {
							if (++$num_consecutive > $maximum_consecutive_lessons) {
								$max_consecutive_violated++;
								last M;
							}
						}
					}
				}
							
				if ($max_consecutive_violated) {
					next RAND_ASSIGN_LOOP;
				}

				my $mut_ex_violated = 0;
				#does this lesson have any mut_ex
				#lesson associations set?
				if ( exists $mut_ex_lessons{lc("$subject($class_0)")} ) {

					CHECK_MUT_EX_1: for my $class_1 (keys %lesson_assignments) {
						my @subjs =  ();
						if (exists ${${$lesson_assignments{$class_1}}{$day}}{$event_cnt}) {
							@subjs = keys %{${${$lesson_assignments{$class_1}}{$day}}{$event_cnt}};
						}

						for my $subj (@subjs) {	
							if (exists ${$mut_ex_lessons{lc("$subject($class_0)")}}{lc("$subj($class_1)")}) {
								$mut_ex_violated++;	
								last CHECK_MUT_EX_1;
							}
						}
					}
				}

				if ($mut_ex_violated) {
					next RAND_ASSIGN_LOOP;
				}

				my $consecutive_violated = 0;
				#consecutive lessons
				if ( exists $consecutive_lessons{lc("$subject($class_0)")} )  {

					my ($step_back,$step_forth) = (1,1);

					my $org = 0;
					if ( exists $exception_days{$day} ) {
						$org = $exception_days{$day};
					}

					#preceding event is a non-lesson; step back farther (1 step farther).
					if ( exists ${$machine_day_orgs{$org}}{$event_cnt - 1} and ${$machine_day_orgs{$org}}{$event_cnt - 1}->{"type"} eq "1" ) {
						$step_back++;
					}

					#subsequent event is a non-lesson: step forth faarther (1 step farther- a correct impl
					#would step forth as far as necessary)
					if ( exists ${$machine_day_orgs{$org}}{$event_cnt + 1} and ${$machine_day_orgs{$org}}{$event_cnt + 1}->{"type"} eq "1" ) {
						$step_forth++;
					}

					CHECK_CONSECUTIVE_SINGLE: for my $class_1 (keys %lesson_assignments) {
						next unless (lc($class_1) eq lc($class_0));
						for my $event_cnt_1 (keys %{${$lesson_assignments{$class_1}}{$day}}) {							
			
							if ( ($event_cnt_1 + $step_back) == $event_cnt or ($event_cnt_1 - $step_forth) == $event_cnt ) {
								#now check if there's a consecutive lesson association
								my @subjs = ();
								if ( exists ${${$lesson_assignments{$class_1}}{$day}}{$event_cnt_1} ) {
									@subjs = keys %{${${$lesson_assignments{$class_1}}{$day}}{$event_cnt_1}};
								}

								for my $subj ( @subjs ) {
									my $lesson = lc ("$subj($class_1)");
									if (exists ${$consecutive_lessons{lc("$subject($class_0)")}}{$lesson}) {
										$consecutive_violated++;
										last CHECK_CONSECUTIVE_SINGLE;	
									}
								}
							}
						}	
					}
				}
				if ($consecutive_violated) {
					next RAND_ASSIGN_LOOP;
				}

				else {
							
					#check any simultaneous lesson associations
					#and include them too.	
					#
					if ( exists $simult_lessons{lc("$subject($class_0)")} ) {

						my @selected_classes_cp = @selected_classes;

						my $num_classes = scalar(@selected_classes_cp);

						for (my $i = 0; $i < $num_classes; $i++)  {

							my $swap_index = int(rand $num_classes);
							my $swap_elem = $selected_classes_cp[$swap_index];
		
							$selected_classes_cp[$swap_index] = $selected_classes_cp[$i];
							$selected_classes_cp[$i] = $swap_elem;
						}

						for my $class_2 (@selected_classes_cp) {
							#added sort to ensure lessons with
							#more periods are assigned first.
							SINGLE_SIMULT_0: for my $lesson_cnt_1 ( sort { ${${$list_lessons{$class_2}}{$b}}{"periods"} <=>  ${${$list_lessons{$class_2}}{$a}}{"periods"} } keys %{$list_lessons{$class_2}} ) {

							next if (not defined ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"subject"});
				
							my $subj = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"subject"};
							my $num_periods_1 = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"periods"};

							if ( exists ${$simult_lessons{lc("$subject($class_0)")}}{lc("$subj($class_2)")} ) {

											
								next unless ( $num_periods_1 == $num_periods );

								my @lesson_teachers_1 = @{$lesson_to_teachers{lc("$subj($class_2)")}};
	
								#check if this spot is available
												
								#avoid double alloc spots
								if ( exists ${${$lesson_assignments{$class_2}}{$day}}{$event_cnt} and keys %{${${$lesson_assignments{$class_2}}{$day}}{$event_cnt}} > 0) {
	
									my @curr_lessons = keys %{${${$lesson_assignments{$class_2}}{$day}}{$event_cnt}};

									for (my $i = 0; $i < @curr_lessons; $i++) {
										#check 
										unless ( exists ${$simult_lessons{lc("$subject($class_0)")}}{lc("$curr_lessons[$i]($class_2)")} ) {	
											#print "X-Debug-$try-failed_simult-$event_cnt: $subject($class_0) | $subj($class_2) occupied by $curr_lessons[$i]($class_2)\r\n";
											$exhausted++;
											last RANDOM_ASSIGNS;
										}
									}
								}

								if (exists ${${${$lesson_assignments{$class_2}}{$day}}{$event_cnt}}{$subj} ) {
									#$exhausted++;
									#last RANDOM_ASSIGNS;
									next;	
								}
								#has this lesson been assigned for
								#the day?
								if (exists ${${$day_assignments{$day}}{$class_2}}{$subj}) {

									my $total_weekly_assigns = 0;
									for my $day (keys %day_assignments) {
										for my $class_3 ( keys %{$day_assignments{$day}} ) {
											next unless (lc($class_3) eq lc($class_2));
											for my $subj ( keys %{${$day_assignments{$day}}{$class_3}} ) {
												$total_weekly_assigns++ if (lc($subj) eq lc($subject));
											}
										}
									}

									unless ( exists $multi_assigns{lc("$subj($class_2)")} and $total_weekly_assigns >= $num_days and ${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"} < 2 and abs(${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} - $event_cnt ) >= $multi_assign_gap ) {
										#an unassignable simult lesson
										#means this timetable wont work.
										#next;
										#print "X-Debug-$try-failed_simult-$event_cnt: $subject($class_0) | $subj($class_2) already assigned\r\n";
										$exhausted++;
										last RANDOM_ASSIGNS;
									}
								}

								#check if teachers are available.
								my $any_teacher_free = 0;
								#my $all_teachers_free = 1;
								for my $lesson_ta_3_b (@lesson_teachers_1) {
									#found probs when checking for TA availability
									#when a teacher is sched'd to teach simult lessons
									#the system will refuse to assign more lessons because
									#the teacher is booked. Changed the code so that it checks 
									#if the lesson that is creating the conflict has a simult assoc
									#with the lessons I'm trying to assign.	
									#$all_teachers_free = 0;
									if (not exists ${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_ta_3_b}) {
										$any_teacher_free = 1;
										last;
									}				
									if (${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_ta_3_b} == $lesson_cnt) {
										$any_teacher_free = 1;
										last;											
									}
									#if (exists ${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_ta_3_b}) {
									#	unless ( ${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_ta_3_b} == $lesson_cnt ) {
									#		$all_teachers_free = 0;
									#	}
									#}
								}

								unless ($any_teacher_free) {
								
									#print "X-Debug-$try-$lesson_cnt: $subj($class_2) | $subject($class_0) assign failed teacher taken\r\n";
									$exhausted++;
									last RANDOM_ASSIGNS;
								}
									
								#don't try to align lessons with
								#different numbers of periods.
																	
								${${${$lesson_assignments{$class_2}}{$day}}{$event_cnt}}{$subj}++;
													
								#assign teacher
	
								for my $lesson_ta_3 (@lesson_teachers_1) {
									${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_ta_3} = $lesson_cnt;
								}
								

								${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"}++;
								${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} = $event_cnt;
								#print "X-Debug-$try-" . $cntr++ . ": set $day x$num_periods $class_2($subj) last assign to $event_cnt\r\n"; 
								$deleted_lessons{$class_2}->{$lesson_cnt_1}++;
								delete $list_lessons{$class_2}->{$lesson_cnt_1};
											
								#redo MULTI_SIMULT_0;
								#last;
								$num_resolved_simults++;
							}
						}
					}
				}
											
				#check any occasional joint lessons scheduled.
				if ( exists $occasional_joint_lessons{lc("$subject($class_0)")} ) {
	
					for my $joint_assoc (keys %{$occasional_joint_lessons{lc("$subject($class_0)")}} ) {
						#does this association hav the right number of lessons?
						next unless ( ${${$occasional_joint_lessons{lc("$subject($class_0)")}}{$joint_assoc}}{"periods"} == $num_periods);

						my @selected_classes_cp = @selected_classes;
	
						my $num_classes = scalar(@selected_classes_cp);

						for (my $i = 0; $i < $num_classes; $i++)  {

							my $swap_index = int(rand $num_classes);
							my $swap_elem = $selected_classes_cp[$swap_index];
		
							$selected_classes_cp[$swap_index] = $selected_classes_cp[$i];
							$selected_classes_cp[$i] = $swap_elem;
						}

						for my $class_2 (@selected_classes_cp) {
							#added sort to ensure lessons with
							#more periods are assigned first.
							SINGLE_OCCASIONAL_JOINT_0: for my $lesson_cnt_1 ( sort { ${${$list_lessons{$class_2}}{$b}}{"periods"} <=>  ${${$list_lessons{$class_2}}{$a}}{"periods"} } keys %{$list_lessons{$class_2}} ) {
				
							my $subj = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"subject"};
							my $num_periods_1 = ${${$list_lessons{$class_2}}{$lesson_cnt_1}}{"periods"};

							next unless ($num_periods_1 == $num_periods);

							my @lesson_teachers_1 = @{$lesson_to_teachers{lc("$subj($class_2)")}};

							if ( exists ${${${$occasional_joint_lessons{lc("$subject($class_0)")}}{$joint_assoc}}{"lessons"}}{lc("$subj($class_2)")} ) {	
							

								#is this spot free?
								#avoid double alloc spots
								if ( exists ${${$lesson_assignments{$class_2}}{$day}}{$event_cnt} and  keys %{${${$lesson_assignments{$class_2}}{$day}}{$event_cnt}} > 0 ) {

									my @curr_lessons = keys %{${${$lesson_assignments{$class_2}}{$day}}{$event_cnt}};

									for (my $i = 0; $i < @curr_lessons; $i++) {
										#check 
										unless ( exists ${$occasional_joint_lessons{lc("$subject($class_0)")}}{lc("$curr_lessons[$i]($class_2)")} ) {	
											$exhausted++;
											last RANDOM_ASSIGNS;
										}
									}
								}


								if (exists ${${${$lesson_assignments{$class_2}}{$day}}{$event_cnt}}{$subj} ) {
									next SINGLE_OCCASIONAL_JOINT_0;	
								}
								#has this lesson been assigned for
								#the day?
								if (exists ${${$day_assignments{$day}}{$class_2}}{$subj}) {

									my $total_weekly_assigns = 0;
									for my $day (keys %day_assignments) {
										for my $class_3 ( keys %{$day_assignments{$day}} ) {
											next unless (lc($class_3) eq lc($class_2));
											for my $subj ( keys %{${$day_assignments{$day}}{$class_3}} ) {
												$total_weekly_assigns++ if (lc($subj) eq lc($subject));
											}
										}
									}

									unless ( exists $multi_assigns{lc("$subj($class_2)")} and $total_weekly_assigns >= $num_days and ${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"} < 2 and abs(${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} - $event_cnt ) >= $multi_assign_gap ) {
										next SINGLE_OCCASIONAL_JOINT_0;	
									}
								}
								#check if teachers are available.
								my $num_engaged_teachers = 0;	
								for my $lesson_ta_3_b (@lesson_teachers_1) {
									if (exists ${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_ta_3_b}) {
										unless (${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_ta_3_b} == $lesson_cnt) {
											#print "X-Debug-5-$try-$lesson_cnt: allow collision $day, $event_cnt\r\n";
											$num_engaged_teachers++;
										}
									}
								}
								if ($num_engaged_teachers == scalar(@lesson_teachers_1)) {
									next SINGLE_OCCASIONAL_JOINT_0;
								}
								
								#don't try to align lessons with
								#different numbers of periods.								
								#my $num_allocs = 0;
							
								#spot taken?
								#next MULTI_OCCASIONAL_JOINT_0 if (exists ${${$lesson_assignments{$class_2}}{$day}}{$possib_locs[$m]});
								
								${${${$lesson_assignments{$class_2}}{$day}}{$event_cnt}}{$subj}++;
								#next MULTI_OCCASIONAL_JOINT_0 if (exists ${${$day_assignments{$day}}{$class_2}}{$subj});
								${${$day_assignments{$day}}{$class_2}}{$subj}->{"num_assigns"}++;
								${${$day_assignments{$day}}{$class_2}}{$subj}->{"last_assign"} = $event_cnt;
								#print "X-Debug-$try-" . $cntr++ . ": set $day x$num_periods $class_2($subj) last assign to $event_cnt\r\n"; 

								$deleted_lessons{$class_2}->{$lesson_cnt_1}++;
								delete $list_lessons{$class_2}->{$lesson_cnt_1};
																
								#assign teacher
								if (not exists $teacher_assignments{$day}) {
									$teacher_assignments{$day} = {};
								}

								if (not exists ${$teacher_assignments{$day}}{$event_cnt}) {
									${$teacher_assignments{$day}}{$event_cnt} = {};
								}

								for my $lesson_ta_3 (@lesson_teachers_1) {
									${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_ta_3} = $lesson_cnt;
								}
								#delete this joint assoc
								delete $occasional_joint_lessons{lc("$subject($class_0)")}->{$joint_assoc}->{"lessons"}->{lc("$subj($class_2)")};
								#have all lessons in this association been chopped? if yes, delete the association.
								#interesting prob--the joint_assoc id is unique for any group of lessons.
								#if u've exhausted one, u can dafely delete the others. 
								

								if (keys %{${${$occasional_joint_lessons{lc("$subject($class_0)")}}{$joint_assoc}}{"lessons"}} == 0) {	
									for my $lesson_2 (keys %occasional_joint_lessons) {
										JJ: for my $joint_assoc_2 (keys %{$occasional_joint_lessons{$lesson_2}} ) {
											if ($joint_assoc_2 == $joint_assoc) {
													
												delete $occasional_joint_lessons{$lesson_2};
													
												last JJ;
											}
										}
									}
									if (scalar(keys %occasional_joint_lessons) == 0) {
												
										%occasional_joint_lessons = ();
									}
								}
								#next MULTI_SIMULT_0;
								#last;
								
							}
						}
					}
				}
			}

			#assign teacher(s) & lessons
			if (not exists $teacher_assignments{$day}) {
				$teacher_assignments{$day} = {};
			}
	
			
			#assign lesson
			if ( not exists ${${$lesson_assignments{$class_0}}{$day}}{$event_cnt} ) {
				${${$lesson_assignments{$class_0}}{$day}}{$event_cnt} = {};
			}

			${${${$lesson_assignments{$class_0}}{$day}}{$event_cnt}}{$subject}++;

			if (not exists ${$teacher_assignments{$day}}{$event_cnt}) {
				${$teacher_assignments{$day}}{$event_cnt} = {};
			}

			#assign teacher
			for my $lesson_ta_2 (@lesson_teachers) {
				${${$teacher_assignments{$day}}{$event_cnt}}{$lesson_ta_2} = $lesson_cnt;
			}	

			#forgot to break out--ended up in a ridiculous loop 
			#then just after that, I forgot to delete the lessson I had
			#just processed.
			${${$day_assignments{$day}}{$class_0}}{$subject}->{"num_assigns"}++;
			${${$day_assignments{$day}}{$class_0}}{$subject}->{"last_assign"} = $event_cnt;

			$deleted_lessons{$class_0}->{$lesson_cnt}++;
			delete $list_lessons{$class_0}->{$lesson_cnt};

			#print "X-Debug-$try-$event_cnt-$class_0" . $cntr++ . ": assigned x$num_periods $subject($class_0)\r\n";
 
			#check if all simult lessons have been proc'd
			if ( exists $simult_lessons{lc("$subject($class_0)")} ) {
				if (not scalar(keys %{$simult_lessons{lc("$subject($class_0)")}}) == $num_resolved_simults) {
					#print "X-Debug-$try-" . $cntr++ . ": simult $subject($class_0) failed\r\n";
					$exhausted++;
					last RANDOM_ASSIGNS;
				}
			}

			last RAND_ASSIGN_LOOP;

		}
		
	}
	
}

#last PP;
	if ($exhausted) {
		#print "X-Debug-$try-" . $cntr++ . ": walkout on PP\r\n"; 
		last PP;
	}
}

#redo RANDOM_ASSIGNS;
	#if ($exhausted) {
	#	print "X-Debug-$try-" . $cntr++ . ": walkout on classes\r\n";
	#	last;
	#}
}

}
			
			#are there any scheduled consecutive lesson associatins 
			#that are unsettled?
			#
			if (scalar(keys %unresolved_consecutive) > 0) {	
				
				$exhausted = 4;
			}

			#had issues with using scalar() to tell if any 
			#occasional joint lessons remained
			#had to use some walk to determine if indeed
			#there were any lessons unasigned.
			#$cntr = 0;
			unless (scalar(keys %occasional_joint_lessons) == 0) {
				for my $key (keys %occasional_joint_lessons) {
					for my $key_2 (keys %{$occasional_joint_lessons{$key}}) {
						for my $key_3 (keys %{${${$occasional_joint_lessons{$key}}{$key_2}}{"lessons"}}) {
							$cntr++;	
						}
					}
				}
			}

			if ($cntr > 0) {
				
				$exhausted = 5;	
			}
			#assign remaining lessons
			
			if ($exhausted) {

				for my $class_y (keys %list_lessons) {
					#print "X-Debug-remaining_lessons-$try-$class_y: " . scalar(keys %{$list_lessons{$class_y}}) . "\r\n";
				}
				 
				#to avoid double-assigning a teacher,
				#record all assignements by the day & event
				#count.
				%teacher_assignments = ();

				#assign lessons
				%list_lessons  = ();
				my $lesson_cntr = 0;

				my @selected_classes_cp = @selected_classes;

				my $num_classes = scalar(@selected_classes_cp);

				for (my $i = 0; $i < $num_classes; $i++)  {

					my $swap_index = int(rand $num_classes);
					my $swap_elem = $selected_classes_cp[$swap_index];
		
					$selected_classes_cp[$swap_index] = $selected_classes_cp[$i];
					$selected_classes_cp[$i] = $swap_elem;
				}

				for my $class_0 (@selected_classes_cp) {
					$list_lessons{$class_0} = {};	

					my %lesson_struct = %default_lesson_structs;
					#are there any exceptional lesson structures for this class? 
					if (exists $exceptional_lesson_structs{lc($class_0)}) {
						for my $struct_id (keys %{$exceptional_lesson_structs{lc($class_0)}}) {
							my $subject = $profile_vals{"lesson_structure_subject_$struct_id"};
							my $struct = $profile_vals{"lesson_structure_struct_$struct_id"};
							$lesson_struct{$subject} = $struct;
						}
					}

					for my $subject (keys %lesson_struct) {
						my @struct = split/,/,$lesson_struct{$subject};
						foreach (@struct) {
							if ($_ =~ /(\d+)x(\d+)/) {
								my $number_lessons     = $1;
								my $periods_per_lesson = $2;
								next if ($number_lessons == 0 or $periods_per_lesson == 0);
								for (my $i = 0; $i < $number_lessons; $i++) {
									${$list_lessons{$class_0}}{$lesson_cntr++} = {"subject" => $subject, "periods" => $periods_per_lesson};

								}
							}
						}
					}
				}	
	
				#reset occasional joint lessons
				for my $profile_name_6 (keys %profile_vals) {
					if ( $profile_name_6 =~ /^lesson_associations_occasional_joint_lessons_([0-9]+)$/ ) {
	
						my $id = $1;
						if (exists $profile_vals{"lesson_associations_occasional_joint_format_$id"}) {

							my @lessons = split/,/,lc($profile_vals{$profile_name_6});
							my @periods = split/,/,$profile_vals{"lesson_associations_occasional_joint_format_$id"};

							for ( my $i = 0; $i < @lessons; $i++ ) {
		
								$total_num_associations{$lessons[$i]}++;
	
								if (not exists $occasional_joint_lessons{$lessons[$i]}) {
									$occasional_joint_lessons{$lessons[$i]} = {};
								}

								if ( not exists ${$occasional_joint_lessons{$lessons[$i]}}{$id} ) {
									${$occasional_joint_lessons{$lessons[$i]}}{$id} = {};
								}

								my @lessons_cp = @lessons;
								splice(@lessons_cp, $i, 1);

								my %lessons_hash;
								@lessons_hash{@lessons_cp} = @lessons_cp;

								for my $period (@periods) {
									if ( $period =~ /^(\d+)x(\d+)$/ ) {
										my $num_lessons = $1;
										my $periods_per_lesson = $2;
										next if ($num_lessons == 0);
										for ( my $j = 0; $j < $num_lessons; $j++ ) {
											${$occasional_joint_lessons{$lessons[$i]}}{$id} = {"lessons" => \%lessons_hash, "periods" => $periods_per_lesson };	
										}
									}
								}
							}
						}
					}
				}

			#re-assign free morns/aftes
			#free up teachers on mornings & afternoons
			#mornings;
			if (exists $profile_vals{"teachers_number_free_mornings"} and $profile_vals{"teachers_number_free_mornings"} =~ /^\d+$/) {

				my %mornings = ();
		
				for my $day_org (keys %machine_day_orgs) {
					my $adds = 0;
					JY: for my $event (sort {$a <=> $b} keys %{$machine_day_orgs{$day_org}}) {
						for my $val ( keys %{${$machine_day_orgs{$day_org}}{$event}} ) {
							#seen 
							if ( $val eq "type" and ${${$machine_day_orgs{$day_org}}{$event}}{"type"} == 1 ) {
								if ($adds > 0) {	
									last JY;
								}
							}
							elsif ($val eq "type" and ${${$machine_day_orgs{$day_org}}{$event}}{"type"} == 0 ) {
								$adds++;
								${$mornings{$day_org}}{$event}++;
							}
						}
					}
				}

				
				my $num_free_morns = $profile_vals{"teachers_number_free_mornings"};

				my @teachers = keys %teachers;
				my $num_tas = scalar(keys %teachers);

				#shuffle teachers
				for (my $i = 0; $i < @teachers; $i++) {
					my $cp = $teachers[$i];
					my $selection = int(rand $num_tas);
					$teachers[$i] = $teachers[$selection];
					$teachers[$selection] = $cp;
				}


				my $cycles = 0;
				for (my $j = 0; $j < $num_free_morns; $j++) {

					my %processed_tas = ();

					for (my $l = 0; $l < @teachers; $l++) {
						#don't double process teachers with simult lessons
						next if (exists $processed_tas{$teachers[$l]});

						my $day = $selected_days_list[$cycles];

						my $day_org = 0;
						if ( exists $exception_days{$day} ) {
							$day_org = $exception_days{$day};
						}
						my @morn_events = keys %{$mornings{$day_org}};
						
						for (my $k = 0; $k < @morn_events; $k++) {
							${${${$teacher_assignments{$teachers[$l]}}}{$day}}{$morn_events[$k]} = -1;

							#check any simults
							my @lessons = @{$teachers{$teachers[$l]}->{"lessons"}};

							for ( my $m = 0; $m < scalar(@lessons); $m++ ) {
								#has simults
								if ( exists $simult_lessons{ lc($lessons[$m]) } ) {
									for my $simult_lesson ( keys %{$simult_lessons{lc($lessons[$m])}} ) {
										#get teachers
										my @tas = @{$lesson_to_teachers{$simult_lesson}};

										#print "X-Debug-2-$try-$j-$teachers[$l]-$m: proc'ng simult dependency $simult_lesson -> " . join(", ", @tas) . "\r\n";

										for ( my $n = 0; $n < scalar(@tas); $n++ ) {
											#free up teacher
											${${${$teacher_assignments{$tas[$n]}}}{$day}}{$morn_events[$k]} = -1;
											#record ta as processed
											$processed_tas{$tas[$n]}++;
										}
									}
								}
							}
						}	

						if (++$cycles >= scalar(@selected_days_list)) {
							$cycles = 0;
						}
					}
				}
			}

			
			#free afternoons.
			if (exists $profile_vals{"teachers_number_free_afternoons"} and $profile_vals{"teachers_number_free_afternoons"} =~ /^\d+$/) {

				my %afternoons = ();
				
				for my $day_org (keys %machine_day_orgs) {
					my $adds = 0;
					JY: for my $event (sort {$b <=> $a} keys %{$machine_day_orgs{$day_org}}) {
						for my $val ( keys %{${$machine_day_orgs{$day_org}}{$event}} ) {
							#seen 
							if ( $val eq "type" and ${${$machine_day_orgs{$day_org}}{$event}}{"type"} == 1 ) {
								if ($adds > 0) {	
									last JY;
								}
							}
							elsif ($val eq "type" and ${${$machine_day_orgs{$day_org}}{$event}}{"type"} == 0 ) {
								$adds++;
								${$afternoons{$day_org}}{$event}++;
							}
						}
					}
				}

				
				my $num_free_aftes = $profile_vals{"teachers_number_free_afternoons"};

				my @teachers = keys %teachers;
				my $num_tas = scalar(keys %teachers);

				#shuffle teachers
				for (my $i = 0; $i < @teachers; $i++) {
					my $cp = $teachers[$i];
					my $selection = int(rand $num_tas);
					$teachers[$i] = $teachers[$selection];
					$teachers[$selection] = $cp;
				}
	
				my $cycles = 0;
				for (my $j = 0; $j < $num_free_aftes; $j++) {
					my %processed_tas = ();
					#my $cycles = 0;
					for (my $l = 0; $l < @teachers; $l++) {

						#don't double process teachers with simult lessons
						next if (exists $processed_tas{$teachers[$l]});

						my $day = $selected_days_list[$cycles];

						my $day_org = 0;
						if ( exists $exception_days{$day} ) {
							$day_org = $exception_days{$day};
						}
						my @afte_events = keys %{$afternoons{$day_org}};
						
						for (my $k = 0; $k < @afte_events; $k++) {
							#free teacher
							${${${$teacher_assignments{$teachers[$l]}}}{$day}}{$afte_events[$k]} = -2;

							#check any simults
							my @lessons = @{$teachers{$teachers[$l]}->{"lessons"}};

							for ( my $m = 0; $m < scalar(@lessons); $m++ ) {
								#has simults
								if ( exists $simult_lessons{ lc($lessons[$m]) } ) {
									for my $simult_lesson ( keys %{$simult_lessons{lc($lessons[$m])}} ) {
										#get teachers
										my @tas = @{$lesson_to_teachers{$simult_lesson}};
										#print "X-Debug-1-$try-$j-$teachers[$l]-$m: proc'ng simult dependency $simult_lesson -> " . join(", ", @tas) . "\r\n";

										for ( my $n = 0; $n < scalar(@tas); $n++ ) {
											#free up teacher
											${${${$teacher_assignments{$tas[$n]}}}{$day}}{$afte_events[$k]} = -2;
											#record ta as processed
											$processed_tas{$tas[$n]}++;
										}
									}
								}
							}
						}

						if (++$cycles >= scalar(@selected_days_list)) {
							$cycles = 0;
						}
					}
				}
			}
				next TRY_MAKE_TIMETABLE;	
			}
	
			else {	
				last TRY_MAKE_TIMETABLE;
			}

			}
#=cut



			if ($exhausted) {
				$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Create Timetable</title>
</head>
<body>
$header
<p><span style="color: red">Could not create timetable. </span>This could be to any of the following issues:<ul>
<li>one or more of the lessons with a fixed scheduling could not be assigned. This usually happens when too many lessons have been restricted to the same periods and/or days. It's strongly recommended that you use <em>fixed scheduling</em> very sparingly.
<li>there're too many lesson associations.
<li>too many free mornings/afternoons have been allocated to each teacher.
Please <a href="/cgi-bin/edittimetableprofiles.cgi?profile=$profile">review this profile</a> to ensure there're no extraneous lessons with fixed scheduling.
*;
				last MAKE_TIMETABLE;
			}
			#values to remember:- @selected_classes, %selected_classes, %exception_days
			#%day_orgs, %machine_day_orgs, %lesson_assignments
				
			my $serial_selected_classes = freeze \@selected_classes;
			my $serial_selected_days = freeze \%selected_days;
			my $serial_exception_days = freeze \%exception_days;
			my $serial_day_orgs = freeze \%day_orgs;
			my $serial_machine_day_orgs = freeze \%machine_day_orgs;
			my $serial_lesson_assignments = freeze \%lesson_assignments;
			my $serial_day_org_num_events = freeze \%day_org_num_events;
			my $serial_lesson_to_teachers = freeze \%lesson_to_teachers;
			my $serial_teachers = freeze \%teachers;
				
			my $timetable_conf_code = gen_token(1);
	
			my $prep_stmt9 = $con->prepare("INSERT INTO timetables VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,?,?)");

			if ($prep_stmt9) {
				my $rc = $prep_stmt9->execute(time, $timetable_conf_code, 0, 0, $serial_selected_classes, $serial_selected_days, $serial_exception_days, $serial_day_orgs, $serial_machine_day_orgs, $serial_lesson_assignments, $serial_day_org_num_events, $serial_lesson_to_teachers, $serial_teachers);

				if ($rc) {
					$con->commit();
				}
				else {
					print STDERR "Could not execute INSERT INTO timetables statement: ", $con->errstr, $/;			
				}
			}
			else {
				print STDERR "Could not create INSERT INTO timetables statement: ", $con->errstr, $/;
			}

			#simply draw the timetable outline.
			$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Create Timetable</title>
$js
</head>
<body>
$header
$feedback
*;

			for my $class (sort {$a cmp $b} @selected_classes) {
				$content .= qq!<p><p><TABLE border="1" cellspacing="0" cellpadding="0">!;

				my $num_cols_plus_1 = $num_cols + 1;
				$content .= qq!<THEAD><TR><TH colspan="$num_cols_plus_1" style="font-weight: bold; text-align: center; font-size: 1.5em">$class</THEAD>!;

				$prev_org = -1;
				foreach my $day ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday") {
					next if (not exists $selected_days{$day});

					my $organization = 0;	
					my $current_org = 0;

					if (exists $exception_days{$day}) {
						$organization = $exception_days{$day};	
						$current_org = $organization;
					}
	
					#draw table head
					if ($current_org != $prev_org) {
						$content .= "<THEAD><TH>&nbsp";
						my $start_lessons = ${$day_orgs{$current_org}}{"start"};
						my ($hrs,$mins) = (0,0);
						my $colon = "";

						if ($start_lessons =~ /^(\d{1,2})(:?)(\d{1,2})$/) {
							$hrs   = $1;
							$mins  = $3;
							$colon = $2;
						}
	
						my $surplus_cols = $num_cols - scalar(keys %{$machine_day_orgs{$current_org}});

						for my $event (sort {$a <=> $b} keys %{$machine_day_orgs{$current_org}}) {

							my $duration = ${${$machine_day_orgs{$current_org}}{$event}}{"duration"};

							my $duration_mins = $duration % 60;
							my $duration_hrs = int($duration / 60);
							
							my $stop_hrs = $hrs + $duration_hrs; 
							my $stop_mins = $mins + $duration_mins;

							if ($stop_mins >= 60) {
								$stop_mins = $stop_mins - 60;
								$stop_hrs++;
							}

						my ($display_hrs,$display_stop_hrs) = ($hrs,$stop_hrs);

						#convert to 12hr clock system
						my $am_pm = "AM";
						if ($display_hrs >= 12) {
							if ($display_hrs > 12) {
								$display_hrs -= 12;
							}

							$am_pm = "PM"; 
						}
						else {
							if ($display_hrs == 0) {
								$display_hrs = 12;
							}	
						}

						if ($display_stop_hrs >= 12) {
							if ($display_stop_hrs > 12) {
								$display_stop_hrs -= 12;
							}
							$am_pm = "PM"; 
						}
						else {
							if ($display_stop_hrs == 0) {
								$display_stop_hrs = 12;
							}	
						}

						($display_hrs,$mins,$display_stop_hrs,$stop_mins) = (sprintf("%02d", $display_hrs), sprintf("%02d", $mins), sprintf("%02d", $display_stop_hrs), sprintf("%02d", $stop_mins));	

						my $time = "${display_hrs}${colon}${mins}${am_pm} - ${display_stop_hrs}${colon}${stop_mins}${am_pm}";
							#($hrs,$mins,$stop_hrs,$stop_mins) = (sprintf("%02d", $hrs), sprintf("%02d", $mins), sprintf("%02d", $stop_hrs), sprintf("%02d", $stop_mins));

							#my $time = "${hrs}${colon}${mins} - ${stop_hrs}${colon}${stop_mins}";
							my $colspan = "";

							$colspan = qq! colspan="2"! if ($surplus_cols-- > 0);
							$content .= qq!<TH${colspan} style="font-weight: bold">$time!;

							$hrs  = $stop_hrs;
							$mins = $stop_mins;
						}
						$content .= "</THEAD>";
					}

					#draw table body
					$content .= qq!<TBODY><TR><TD style="font-weight: bold">$day!;
				
					my $surplus_cols = $num_cols - scalar(keys %{$machine_day_orgs{$current_org}});

					for my $event (sort {$a <=> $b} keys %{$machine_day_orgs{$current_org}}) {
						my $name = "-";
						$name = join("<BR>", keys %{${${$lesson_assignments{$class}}{$day}}{$event}}) if (exists ${${$lesson_assignments{$class}}{$day}}{$event} and  scalar ( keys %{${${$lesson_assignments{$class}}{$day}}{$event}}) > 0);
						my $colspan = "";
						$colspan = qq! colspan="2"! if ($surplus_cols-- > 0);

						#Bold the fixed name events (might be things like 'Lunch')
						if ( $machine_day_orgs{$current_org}->{$event}->{"type"} == 1 ) {
							$content .= qq!<TD${colspan} style="font-weight: bold">$name!;
						}
						else {
							$content .= qq!<TD${colspan}>$name!;
						}
					}
					$prev_org = $current_org;
				}

				$content .= "</TABLE>";
			}

			my $conf_code = gen_token();
			$session{"confirm_code"} = $conf_code;

			$content .=
qq!
<HR>
<DIV>
<FORM method="POST" action="/cgi-bin/createtimetable.cgi" onsubmit="document.getElementById('pub_download_button').value = 'Timetable published\!'; document.getElementById('pub_download_button').style.color = 'green'">
<INPUT type="hidden" name="timetable_conf_code" value="$timetable_conf_code">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<INPUT type="submit" name="pub_download" value="Publish & Download" id="pub_download_button">
</FORM>
</DIV>
!;
			last MAKE_TIMETABLE;
		}
		else {
			my $select_one = "";
			if (keys %existing_profiles) {
				$select_one = " Select one of the profiles in the menu.";
			}

			$feedback .= qq!<p><span style="color: red">Invalid profile selected.$select_one</span>!;
			$post_mode = 0;
		}
	}
	#request the profile again.
	#maybe I'm a little trapped by this 
	#'confirm code' biz.
	else {
		$feedback = qq!<p><span style="color: red">Invalid request sent. Do not modify the hidden values in this HTML form.</span>!;
		$post_mode = 0;
	}
}
}
#ask the user to specify the profile to use
if (not $post_mode) {
	$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Create Timetable</title>
</head>
<body>
$header
$feedback
*;

	if (keys %existing_profiles) {

		my $conf_code = gen_token();
		$session{"confirm_code"} = $conf_code;

		$content .= 
qq!<FORM method="POST" action="/cgi-bin/createtimetable.cgi">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<TABLE>
<TR>
<TD><LABEL for="profile">What profile would you like to use?</LABEL>
<TD><SELECT name="profile">!;

		for my $profile (keys %existing_profiles) {
			$content .= qq!<OPTION value="$profile" title="${$existing_profiles{$profile}}{"name"}">${$existing_profiles{$profile}}{"name"}</OPTION>!;
		}

		$content .= "</SELECT>";
		$content .=
qq!
<TR>
<TD><INPUT type="submit" name="create" value="Create Timetable">
<TD>&nbsp;
</TABLE>
</FORM>
!;	
	}
	else {
		$content .= qq!<p><span style="color: red">No timetable profile has been created yet.</span> To use Yans, you must have a <em>profile</em> that defines such things as when classes start. Would you like to <a href="/cgi-bin/edittimetableprofiles.cgi">create a profile</a> now?!;
	}

	$content .= "</body></html>";
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

sub associations_sorter {

	my $b_val = 0;
	if (exists $total_num_associations{lc(${$fixed_scheduling{$b}}{"subject"} . "(" . ${$fixed_scheduling{$b}}{"class"} . ")")}) {
		$b_val = $total_num_associations{lc(${$fixed_scheduling{$b}}{"subject"} . "(" . ${$fixed_scheduling{$b}}{"class"} . ")")};
	}

	my $a_val = 0;
	if (exists $total_num_associations{lc(${$fixed_scheduling{$a}}{"subject"} . "(" . ${$fixed_scheduling{$a}}{"class"} . ")")}) {
		$a_val = $total_num_associations{lc(${$fixed_scheduling{$a}}{"subject"} . "(" . ${$fixed_scheduling{$a}}{"class"} . ")")};
	}

	my $cmp_1 = $b_val <=> $a_val;

	return $cmp_1 unless ($cmp_1 == 0);

	
	return scalar(@{${$fixed_scheduling{$a}}{"periods"}}) <=> scalar(@{${$fixed_scheduling{$b}}{"periods"}});
}

